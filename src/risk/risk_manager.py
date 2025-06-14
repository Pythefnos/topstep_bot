import logging

logger = logging.getLogger(__name__)

class RiskManager:
    """
    Risk management module enforcing Topstep rules:
    - Daily Loss Limit (DLL)
    - Max Trailing Drawdown (MDD)
    Also handles trading hour cutoffs and emergency kill-switch triggers.
    """
    def __init__(self, starting_balance: float, daily_loss_limit: float, max_drawdown: float):
        self.starting_balance = starting_balance
        self.daily_loss_limit = daily_loss_limit
        self.max_drawdown = max_drawdown
        # Dynamic tracking
        self.daily_start_balance = starting_balance
        self.current_balance = starting_balance
        self.peak_balance = starting_balance
        self.trailing_threshold = starting_balance - max_drawdown  # balance level that if breached triggers fail
        self.daily_realized_pl = 0.0
        self.trading_disabled = False  # becomes True if a risk limit is hit (to stop further trading)

        logger.info(f"RiskManager initialized: starting_balance={starting_balance}, "
                    f"daily_loss_limit={daily_loss_limit}, max_drawdown={max_drawdown}")

    def reset_day(self):
        """Reset daily counters at the start of a new trading day."""
        self.daily_start_balance = self.current_balance
        self.daily_realized_pl = 0.0
        logger.info(f"Daily start balance set to {self.daily_start_balance:.2f} for new day.")

    def update_after_trade(self, profit_loss: float):
        """
        Update balances and risk tracking after a trade is closed (realized P&L).
        """
        self.daily_realized_pl += profit_loss
        self.current_balance += profit_loss
        # Update peak balance if new balance is a high watermark
        if self.current_balance > self.peak_balance:
            self.peak_balance = self.current_balance
            self.trailing_threshold = self.peak_balance - self.max_drawdown
            logger.info(f"New peak balance achieved: {self.peak_balance:.2f}. "
                        f"Updated trailing drawdown threshold to {self.trailing_threshold:.2f}.")
        # Check risk limits after this trade
        if self.current_balance < self.trailing_threshold:
            # Trailing drawdown breached
            self.trading_disabled = True
            logger.error("Trailing drawdown limit breached! Current balance fell below allowed threshold.")
        # Check daily loss limit (compare current balance vs daily start)
        if self.current_balance <= self.daily_start_balance - self.daily_loss_limit:
            self.trading_disabled = True
            logger.error("Daily loss limit breached! Current balance fell below daily loss threshold.")

    def allow_new_trade(self) -> bool:
        """
        Check if a new trade is allowed under current risk conditions.
        For instance, if already very close to daily loss limit or drawdown, new trades might be disallowed.
        Currently, this returns False if trading_disabled flag is set.
        """
        if self.trading_disabled:
            return False
        # Additional checks can be implemented here (e.g., if current unrealized loss is near limits).
        return True

    def check_real_time_risk(self, unrealized_pl: float) -> bool:
        """
        Check risk limits including unrealized P&L of open positions.
        If adding the unrealized P&L to current balance violates any limit, return True (violation).
        """
        if self.trading_disabled:
            return True
        # Calculate hypothetical equity if we closed position now
        equity = self.current_balance + unrealized_pl
        # Trailing drawdown check
        if equity < self.trailing_threshold:
            self.trading_disabled = True
            logger.error(f"Trailing drawdown would be breached by unrealized loss! Equity {equity:.2f} < threshold {self.trailing_threshold:.2f}.")
            return True
        # Daily loss limit check
        if equity <= self.daily_start_balance - self.daily_loss_limit:
            self.trading_disabled = True
            logger.error(f"Daily loss limit would be breached by unrealized loss! Equity {equity:.2f} below daily threshold {self.daily_start_balance - self.daily_loss_limit:.2f}.")
            return True
        return False

    def calculate_pnl(self, entry_price: float, exit_price: float, size: int, point_value: float) -> float:
        """
        Calculate the profit or loss for a closed trade.
        entry_price, exit_price: price at entry and exit.
        size: positive for long position size, negative for short.
        point_value: monetary value per 1.0 price move for the instrument.
        """
        if size == 0:
            return 0.0
        # For long positions, P/L = (exit - entry) * size * point_value
        # For short positions, P/L = (entry - exit) * |size| * point_value
        pl = (exit_price - entry_price) * size * point_value
        return pl

    def check_kill_switch(self) -> bool:
        """
        Check if an emergency kill-switch (e.g., YubiKey trigger) is activated.
        This is a stub for future implementation.
        Returns True if kill-switch is triggered (in real usage, integrate with hardware or user input).
        """
        # TODO: Integrate actual YubiKey or external signal check for emergency stop.
        return False
