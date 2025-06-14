import logging
from collections import deque
from typing import Optional

logger = logging.getLogger(__name__)

class BasicStrategy:
    """
    A basic Moving Average Crossover strategy.
    Uses a short-term and a long-term moving average of price to determine signals.
    - When the short-term MA crosses above the long-term MA, signals a LONG.
    - When the short-term MA crosses below the long-term MA, signals a SHORT.
    """
    def __init__(self, short_window: int, long_window: int):
        if short_window <= 0 or long_window <= 0:
            raise ValueError("MA window lengths must be positive integers.")
        self.short_window = short_window
        self.long_window = long_window
        # Deques to store recent prices for MA calculations
        self.short_prices = deque(maxlen=short_window)
        self.long_prices = deque(maxlen=long_window)
        # Running sums for efficient moving average computation
        self.short_sum = 0.0
        self.long_sum = 0.0

    def recommend_position(self, price: float) -> Optional[int]:
        """
        Update with the latest price and return a recommended position:
        +1 for long, -1 for short, 0 for neutral (no change).
        Returns None if not enough data yet to make a decision.
        """
        # Update long-term price deque and sum
        self.long_prices.append(price)
        self.long_sum += price
        if len(self.long_prices) > self.long_window:
            oldest_long = self.long_prices.popleft()
            self.long_sum -= oldest_long

        # Update short-term price deque and sum
        self.short_prices.append(price)
        self.short_sum += price
        if len(self.short_prices) > self.short_window:
            oldest_short = self.short_prices.popleft()
            self.short_sum -= oldest_short

        # Only proceed if we have enough data for the long-term MA
        if len(self.long_prices) < self.long_window:
            return None  # not enough data to compute long-term MA yet

        # Compute moving averages
        short_ma = self.short_sum / len(self.short_prices)
        long_ma = self.long_sum / len(self.long_prices)
        # Determine position signal
        if short_ma > long_ma:
            return 1    # signal to be long
        elif short_ma < long_ma:
            return -1   # signal to be short
        else:
            return 0    # moving averages equal -> no clear signal (hold current position)
