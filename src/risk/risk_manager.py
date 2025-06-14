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
        self.trailing_threshold = starting_balance - max_drawdown  # balance level that triggers failure if breached
        self.daily_realized_pl = 0.0
        self.trading_disabled = False  # set to True if a risk limit is hit (disables new trades)

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
        # Update peak balance and trailing threshold if a new high is achieved
        if self.current_balance > self.peak_balance:
            self.peak_balance = self.current_balance
            self.trailing_threshold = self.peak_balance - self.max_drawdown
            logger.info(f"New peak balance achieved: {self.peak_balance:.2f}. "
                        f"Updated trailing drawdown threshold to {self.trailing_threshold:.2f}.")
        # Check trailing drawdown limit
        if self.current_balance < self.trailing_threshold:
            self.trading_disabled = True
            logger.error("Trailing drawdown limit breached! Current balance fell below allowed threshold.")
        # Check daily loss limit (compare current balance vs daily start)
        if self.current_balance <= self.daily_start_balance - self.daily_loss_limit:
            self.trading_disabled = True
            logger.error("Daily loss limit breached! Current balance fell below daily loss threshold.")

    def allow_new_trade(self) -> bool:
        """
        Determine if a new trade is allowed under current risk conditions.
        Currently returns False if trading_disabled flag is set.
        (Additional pre-trade risk checks can be added here if needed.)
        """
        return not self.trading_disabled

    def check_real_time_risk(self, unrealized_pl: float) -> bool:
        """
        Check risk limits including unrealized P&L of open positions.
        If adding the unrealized P&L to current balance violates any limit, return True (violation).
        """
        if self.trading_disabled:
            return True
        # Hypothetical equity if we closed the position now
        equity = self.current_balance + unrealized_pl
        # Trailing drawdown check with unrealized
        if equity < self.trailing_threshold:
            self.trading_disabled = True
            logger.error(f"Trailing drawdown would be breached by unrealized loss! Equity {equity:.2f} < threshold {self.trailing_threshold:.2f}.")
            return True
        # Daily loss limit check with unrealized
        if equity <= self.daily_start_balance - self.daily_loss_limit:
            self.trading_disabled = True
            logger.error(f"Daily loss limit would be breached by unrealized loss! Equity {equity:.2f} below daily threshold {(self.daily_start_balance - self.daily_loss_limit):.2f}.")
            return True
        return False

    def calculate_pnl(self, entry_price: float, exit_price: float, size: int, point_value: float) -> float:
        """
        Calculate the profit or loss for a closed trade.
        For long positions: P/L = (exit_price - entry_price) * size * point_value
        For short positions: P/L = (entry_price - exit_price) * |size| * point_value
        """
        if size == 0 or point_value is None:
            return 0.0
        # For long positions (size > 0), formula yields profit if exit > entry.
        # For short positions (size < 0), using size (negative) yields profit if exit < entry.
        return (exit_price - entry_price) * size * point_value

    def check_kill_switch(self) -> bool:
        """
        Check if an emergency kill-switch (e.g., a hardware trigger) is activated.
        Stub implementation: always returns False (no kill-switch integrated).
        """
        # TODO: Integrate actual kill-switch (e.g., YubiKey or external signal) for immediate stop.
        return False
