import pytest

from kol_sniper.strategy import parse_exit_ladder, trade_price


def test_exit_ladder_is_sorted_and_bounded() -> None:
    steps = parse_exit_ladder("5:0.25,2:0.5")
    assert [step.multiple for step in steps] == [2, 5]
    with pytest.raises(ValueError):
        parse_exit_ladder("2:0.75,3:0.5")


def test_trade_price_prefers_virtual_reserves() -> None:
    assert trade_price({"vSolInBondingCurve": 20_000_000_000, "vTokensInBondingCurve": 10_000_000}) == 2
    assert trade_price({"solAmount": 3, "tokenAmount": 2}) == 1.5
