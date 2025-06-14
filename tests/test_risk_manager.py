import pytest
from src.risk.risk_manager import RiskManager

def test_daily_loss_limit_violation():
    rm = RiskManager(starting_balance=50_000,
                     daily_loss_limit=1_000,
                     max_drawdown=2_000)

    # Realised loss of -1 200 should breach daily limit
    rm.update_after_trade(-1_200)
    assert rm.trading_disabled, "Trading should be disabled after daily loss breach"

def test_trailing_drawdown_violation():
    rm = RiskManager(starting_balance=50_000,
                     daily_loss_limit=1_000,
                     max_drawdown=2_000)

    # Force equity below trailing threshold
    rm.update_after_trade(-2_100)
    assert rm.trading_disabled, "Trading should be disabled after trailing drawdown breach"

def test_unrealized_risk_check():
    rm = RiskManager(starting_balance=50_000,
                     daily_loss_limit=1_000,
                     max_drawdown=2_000)

    # Unrealized loss that would violate daily limit
    assert rm.check_real_time_risk(unrealized_pl=-1_100), "Unrealized loss should trigger risk stop"
