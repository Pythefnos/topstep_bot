import pytest
from src.strategy.basic_strategy import BasicStrategy

def test_ma_crossover_logic():
    strat = BasicStrategy(short_window=3, long_window=5)
    prices = [100, 101, 102, 103, 104, 105]
    signals = []
    for p in prices:
        sig = strat.recommend_position(p)
        signals.append(sig)

    # After first 5 prices, short MA (avg of last 3) > long MA (avg of last 5) -> expect long (+1)
    assert signals[-1] == 1, "Strategy should signal long after bullish crossover"
