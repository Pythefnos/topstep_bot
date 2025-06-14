import logging

logger = logging.getLogger(__name__)

class RiskManager:
    """
    Risk management module enforcing Topstep rules:
    - Daily Loss Limit
    - Max Trailing Drawdown
    Provides daily resets and an emergency kill-switch stub.
    """
    def __init__(self, starting_balance: float, daily_loss_limit: float, max_drawdown: float):
        self.starting_balance = starting_balance
        self.daily_loss_limit = daily_loss_limit
        self.max_drawdown = max_drawdown
        # Dynamic tracking
        self.daily_start_balance = starting_balance
        self.current_balance = starting_balance
        self.peak_balance = starting_balance
        self.trailing_threshold = starting_balance - max_drawdown  # balance threshold that would breach trailing drawdown
        self.daily_realized_pl = 0.0
        self.trading_disabled = False  # True if any risk limit is hit (blocks new trades)

        logger.info(f"RiskManager initialized: starting_balance={starting_balance:.2f}, "
                    f"daily_loss_limit={daily_loss_limit:.2f}, max_drawdown={max_drawdown:.2f}")

    def reset_day(self):
        """Reset daily loss tracking at the start of a new trading day."""
        self.daily_start_balance = self.current_balance
        self.daily_realized_pl = 0.0
        logger.info(f"Daily start balance set to {self.daily_start_balance:.2f} for new day.")

    def update_after_trade(self, profit_loss: float):
        """
        Update balances and risk metrics after a trade is closed (realized P&L).
        """
        self.daily_realized_pl += profit_loss
        self.current_balance += profit_loss
        # Update peak balance and trailing threshold if a new high is reached
        if self.current_balance > self.peak_balance:
            self.peak_balance = self.current_balance
            self.trailing_threshold = self.peak_balance - self.max_drawdown
            logger.info(f"New peak balance achieved: {self.peak_balance:.2f}. "
                        f"Updated trailing drawdown threshold to {self.trailing_threshold:.2f}.")
        # Check trailing drawdown breach
        if self.current_balance < self.trailing_threshold:
            self.trading_disabled = True
            logger.error(f"Trailing drawdown limit breached! Balance {self.current_balance:.2f} fell below threshold {self.trailing_threshold:.2f}.")
        # Check daily loss limit breach
        if self.current_balance <= self.daily_start_balance - self.daily_loss_limit:
            self.trading_disabled = True
            logger.error(f"Daily loss limit breached! Balance {self.current_balance:.2f} fell below daily threshold {(self.daily_start_balance - self.daily_loss_limit):.2f}.")

    def allow_new_trade(self) -> bool:
        """
        Determine if a new trade is allowed under current risk conditions.
        Returns False if trading_disabled is True.
        """
        return not self.trading_disabled

    def check_real_time_risk(self, unrealized_pl: float) -> bool:
        """
        Check risk limits including unrealized P&L of open positions.
        If current_balance plus unrealized P&L would breach a limit, return True (violation).
        """
        if self.trading_disabled:
            return True
        equity = self.current_balance + unrealized_pl
        # Trailing drawdown check with unrealized P&L
        if equity < self.trailing_threshold:
            self.trading_disabled = True
            logger.error(f"Trailing drawdown would be breached by unrealized loss! Equity {equity:.2f} < threshold {self.trailing_threshold:.2f}.")
            return True
        # Daily loss limit check with unrealized P&L
        if equity <= self.daily_start_balance - self.daily_loss_limit:
            self.trading_disabled = True
            logger.error(f"Daily loss limit would be breached by unrealized loss! Equity {equity:.2f} below daily threshold {(self.daily_start_balance - self.daily_loss_limit):.2f}.")
            return True
        return False

    def calculate_pnl(self, entry_price: float, exit_price: float, size: int, point_value: float) -> float:
        """
        Calculate profit or loss for a closed trade.
        For longs: P/L = (exit_price - entry_price) * size * point_value
        For shorts: P/L = (entry_price - exit_price) * |size| * point_value
        """
        if size == 0 or point_value is None:
            return 0.0
        return (exit_price - entry_price) * size * point_value

    def check_kill_switch(self) -> bool:
        """
        Stub for an emergency kill-switch (external trigger to stop trading).
        Always returns False (no kill-switch implemented).
        """
        # TODO: Integrate actual kill-switch (e.g., hardware or external signal) if required.
        return False
