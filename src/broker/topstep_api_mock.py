import logging

logger = logging.getLogger(__name__)

class TopstepAPIMock:
    """
    A mock Topstep API for simulation mode (dry-run).
    Simulates account balance changes and order placements without real trading.
    """
    def __init__(self, initial_balance: float = 0.0, profit_per_trade: float = 0.0):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.profit_per_trade = profit_per_trade
        self.order_count = 0
        logger.info(f"TopstepAPIMock initialized with starting balance ${self.balance:.2f}.")

    def place_order(self, symbol: str, quantity: float, price: float, side: str):
        """
        Simulate placing an order. Immediately 'fills' the order and updates balance with profit.
        """
        self.order_count += 1
        # Simulate profit for the trade (for demonstration, always profit_per_trade).
        profit = self.profit_per_trade
        self.balance += profit
        logger.info(f"Simulated {side} order #{self.order_count}: {symbol} x {quantity} at {price:.2f}. Profit: ${profit:.2f}. New balance: ${self.balance:.2f}.")
        return {
            "order_id": f"SIM-{self.order_count}",
            "symbol": symbol,
            "quantity": quantity,
            "price": price,
            "side": side,
            "profit": profit
        }

    def get_balance(self):
        """
        Get the current simulated account balance.
        """
        return self.balance
