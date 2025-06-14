import pytest
from src.risk.risk_manager import RiskManager

def test_daily_loss_limit_violation():
    rm = RiskManager(starting_balance=50_000, daily_loss_limit=1_000, max_drawdown=2_000)
    # Realized loss of -1200 should breach the daily loss limit
    rm.update_after_trade(-1_200)
    assert rm.trading_disabled, "Trading should be disabled after daily loss limit breach"

def test_trailing_drawdown_violation():
    rm = RiskManager(starting_balance=50_000, daily_loss_limit=1_000, max_drawdown=2_000)
    # Force equity below trailing threshold (breach trailing drawdown)
    rm.update_after_trade(-2_100)
    assert rm.trading_disabled, "Trading should be disabled after trailing drawdown breach"

def test_unrealized_risk_check():
    rm = RiskManager(starting_balance=50_000, daily_loss_limit=1_000, max_drawdown=2_000)
    # An unrealized loss that would violate the daily loss limit
    assert rm.check_real_time_risk(unrealized_pl=-1_100), "Unrealized loss should trigger risk stop"

def test_trailing_threshold_update_and_no_breach():
    rm = RiskManager(starting_balance=50_000, daily_loss_limit=1_000, max_drawdown=2_000)
    # Simulate a profit to raise peak balance
    rm.update_after_trade(1_500)
    assert rm.current_balance == 51_500
    assert rm.peak_balance == 51_500
    assert rm.trailing_threshold == 49_500  # peak 51500 - 2000
    assert not rm.trading_disabled
    # Simulate a moderate loss that stays within limits
    rm.update_after_trade(-1_000)
    assert rm.current_balance == 50_500  # 51,500 - 1,000
    assert rm.peak_balance == 51_500  # peak remains unchanged
    assert rm.trailing_threshold == 49_500  # unchanged (still peak - 2000)
    assert not rm.trading_disabled, "Trading should remain enabled for a loss within limits"

def test_daily_reset():
    rm = RiskManager(starting_balance=50_000, daily_loss_limit=1_000, max_drawdown=2_000)
    # Simulate some end-of-day P/L
    rm.update_after_trade(500)
    prev_balance = rm.current_balance
    rm.reset_day()
    assert rm.daily_start_balance == prev_balance, "Daily start balance should reset to previous balance"
    assert rm.daily_realized_pl == 0.0, "Daily realized P&L should reset to 0"
    assert not rm.trading_disabled, "Trading should remain enabled if no limits were breached"
