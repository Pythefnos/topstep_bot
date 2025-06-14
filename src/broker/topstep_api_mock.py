import logging

logger = logging.getLogger(__name__)

class TopstepAPIMock:
    """
    A mock Topstep API for simulation (offline) mode.
    Simulates account balance changes and provides dummy market data.
    """
    def __init__(self, initial_balance: float = 0.0, profit_per_trade: float = 0.0, symbol: str = "SIM"):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.profit_per_trade = profit_per_trade
        self.order_count = 0
        self.symbol_id = symbol  # mimic contract identifier
        logger.info(f"TopstepAPIMock initialized with starting balance ${self.balance:.2f}.")

    def connect(self):
        """Simulate API connection (no real authentication needed)."""
        logger.info("TopstepAPIMock connected (simulation mode).")

    def get_latest_price(self) -> float:
        """Return a simulated market price (monotonically increasing for simplicity)."""
        if not hasattr(self, '_last_price'):
            self._last_price = 100.0
        else:
            self._last_price += 1.0
        return self._last_price

    def place_order(self, symbol: str, side: str, size: int) -> str:
        """Simulate placing a market order and immediately 'fill' it with a fixed profit outcome."""
        self.order_count += 1
        # Simulate a fixed profit for each trade (could be set negative to simulate losses)
        profit = self.profit_per_trade
        self.balance += profit
        logger.info(f"Simulated {side.upper()} order #{self.order_count}: {symbol} x {size}. Profit: ${profit:.2f}. New balance: ${self.balance:.2f}.")
        order_id = f"SIM-{self.order_count}"
        return order_id

    def flatten_position(self, symbol: str, size: int, side: str) -> str:
        """Simulate flattening a position by placing an opposite order."""
        return self.place_order(symbol=symbol, side=side, size=size)

    def get_balance(self) -> float:
        """Get the current simulated account balance."""
        return self.balance

    def get_starting_balance(self) -> float:
        """Retrieve the initial account balance (for parity with real API method)."""
        return self.initial_balance
