import pytest
from src.strategy.basic_strategy import BasicStrategy

def test_ma_crossover_logic():
    strat = BasicStrategy(short_window=3, long_window=5)
    prices = [100, 101, 102, 103, 104, 105]
    signals = []
    for p in prices:
        signals.append(strat.recommend_position(p))
    # After feeding 5 prices, short MA > long MA -> expect long (+1)
    assert signals[-1] == 1, "Strategy should signal long after bullish crossover"

def test_no_signal_until_ready():
    strat = BasicStrategy(short_window=3, long_window=5)
    prices = [100, 101, 102, 103]  # 4 prices (one short of long_window)
    signals = [strat.recommend_position(p) for p in prices]
    assert all(sig is None for sig in signals), "Strategy should return None until long_window data is available"

def test_short_signal():
    strat = BasicStrategy(short_window=3, long_window=5)
    prices = [105, 104, 103, 102, 101, 100]  # descending prices
    final_signal = None
    for p in prices:
        final_signal = strat.recommend_position(p)
    # After feeding 5 prices, short MA < long MA -> expect short (-1)
    assert final_signal == -1, "Strategy should signal short after bearish crossover"

def test_equal_ma_signal():
    strat = BasicStrategy(short_window=2, long_window=4)
    prices = [100, 100, 100, 100]  # constant prices
    signals = [strat.recommend_position(p) for p in prices]
    # After feeding 4 prices, short MA == long MA -> expect 0 (no clear signal)
    assert signals[-1] == 0, "Strategy should signal 0 when moving averages are equal"
