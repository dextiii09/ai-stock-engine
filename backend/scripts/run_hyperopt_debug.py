import sys
import os
import traceback

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from analytics.hyperopt import objective, load_live_trades_and_journal

class MockTrial:
    def suggest_float(self, name, low, high, log=False):
        return (low + high) / 2

closed_trades, journal = load_live_trades_and_journal()
trial = MockTrial()

try:
    objective(trial, closed_trades, journal)
except Exception as e:
    traceback.print_exc()
