import logging
from collections import deque
from typing import Optional

logger = logging.getLogger(__name__)

class BasicStrategy:
    """
    A basic Moving Average Crossover strategy.
    Uses a short-term and a long-term moving average of price to generate signals.
    - When the short-term MA crosses above the long-term MA, signal LONG (+1).
    - When the short-term MA crosses below the long-term MA, signal SHORT (-1).
    """
    def __init__(self, short_window: int, long_window: int):
        if short_window <= 0 or long_window <= 0:
            raise ValueError("MA window lengths must be positive integers.")
        self.short_window = short_window
        self.long_window = long_window
        # Deques to store recent prices for moving average calculations
        self.short_prices = deque()
        self.long_prices = deque()
        # Running sums for efficient moving average computation
        self.short_sum = 0.0
        self.long_sum = 0.0

    def recommend_position(self, price: float) -> Optional[int]:
        """
        Update internal state with the latest price and return recommended position:
        +1 for long, -1 for short, 0 for no change.
        Returns None if not enough data yet to determine a signal.
        """
        # Update long-term prices and sum
        self.long_prices.append(price)
        self.long_sum += price
        if len(self.long_prices) > self.long_window:
            oldest_long = self.long_prices.popleft()
            self.long_sum -= oldest_long

        # Update short-term prices and sum
        self.short_prices.append(price)
        self.short_sum += price
        if len(self.short_prices) > self.short_window:
            oldest_short = self.short_prices.popleft()
            self.short_sum -= oldest_short

        # If we don't yet have enough data for the long-term MA, no signal
        if len(self.long_prices) < self.long_window:
            return None

        # Compute moving averages
        short_ma = self.short_sum / len(self.short_prices)
        long_ma = self.long_sum / len(self.long_prices)
        # Determine signal
        if short_ma > long_ma:
            return 1   # go long
        elif short_ma < long_ma:
            return -1  # go short
        else:
            return 0   # averages equal -> no clear signal
