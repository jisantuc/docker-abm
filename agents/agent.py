from collections import Counter
import json
import logging
import random
from string import ascii_letters
import time
import redis

AGENT_ID = ''.join(random.choice(ascii_letters) for _ in range(10))
RULES_BASED = random.choice([True, False])
FORMAT_STR = '%(asctime)s {agent_id} {rules} %(message)s'.format(
    agent_id=AGENT_ID, rules=RULES_BASED)
logging.basicConfig(format=FORMAT_STR, level=logging.DEBUG)
LOGGER = logging.getLogger(__name__)


class Agent(object):
    def __init__(self):
        # Create a connection to the cache and the subscription to the prices
        # we care about
        self.redis_conn = redis.StrictRedis(host='redis', port=6379, db=0)
        self.pubsub_conn = self.redis_conn.pubsub(
            ignore_subscribe_messages=True)
        self.pubsub_conn.subscribe('widget-market')

        # Choose randomly whether to update from rules or randomly
        self.rules_based = RULES_BASED

        # Create a dictionary of goods and this agent's expected future prices for
        # them. This is mainly for future-proofing so that someday there can be
        # more than one kind of good, but for now it's just widgets.
        # If this is the first agent, then we'll assume that the starting widget
        # price is 5
        self.expected_prices = {
            'widget':
            self.get_good_price('widget') + random.normalvariate(0, 1)
        }

    def get_good_price(self, good='widget'):
        price = self.redis_conn.get(good)
        return float(price) if price else 5

    def initialize_good_price(self, good='widget', default_price=5):
        self.redis_conn.set(good, default_price)

    def decrease_expected_price(self, good='widget'):
        self.expected_prices[good] = max(
            self.expected_prices[good] - self.learning_rate, 0.01)

    def make_order_message(self, price):
        return json.dumps({'transaction_type': 'order', 'price': price})

    def make_list_message(self, price):
        return json.dumps({'transaction_type': 'list', 'price': price})

    def increase_expected_price(self, good='widget'):
        self.expected_prices[good] += self.learning_rate

    def update_expectations(self):
        msgs_since_last_check = []
        msg = self.pubsub_conn.get_message()
        while msg:
            msgs_since_last_check.append(msg)
        transactions = [x['data'] for x in msgs_since_last_check]
        trends = Counter([x['transaction_type'] for x in transactions])
        if not self.rules_based:
            self.expected_prices['widget'] = max(
                self.expected_prices['widget'] + random.normalvariate(0, 2),
                0.01)
        elif trends['list'] > trends['order'] + 3:
            self.decrease_expected_price()
        elif trends['order'] > trends['list'] + 3:
            self.increase_expected_price()

    def run(self):
        good = 'widget'
        while True:
            good_price = self.get_good_price('widget')
            expected_good_price = self.expected_prices[good]
            spread = expected_good_price - good_price
            transaction_price = good_price + spread / 2.
            if expected_good_price > good_price:
                LOGGER.info('BUY at %s', transaction_price)
                self.redis_conn.set('widget', transaction_price)
                self.redis_conn.publish(
                    'widget-market',
                    self.make_order_message(transaction_price))
            elif expected_good_price < good_price:
                LOGGER.info('SELL at %s', transaction_price)
                self.redis_conn.set('widget', transaction_price)
                self.redis_conn.publish(
                    'widget-market', self.make_list_message(transaction_price))
            self.update_expectations()
            time.sleep(max(random.uniform(0, 10), 3))
