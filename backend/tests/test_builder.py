import asyncio

import pytest

from zirak.llm.builder import build_strategy, parse_rules
from zirak.llm.provider import MockLLM
from zirak.strategy.spec import StrategySpec


def test_example_sentence() -> None:
    r = parse_rules("وقتی بیت‌کوین ۵٪ ریخت، با ۱۰٪ سرمایه بخر و با ۳٪ سود بفروش")
    assert r.spec is not None, r.error_fa
    s = r.spec
    assert s.symbol == "BTCTMN" and s.resolution == "1h"
    assert s.entry[0].kind == "drop_from_high" and s.entry[0].pct == 5 and s.entry[0].lookback == 24
    assert s.position_size_pct == 10 and s.take_profit_pct == 3
    assert s.stop_loss_pct == 5  # safety default added...
    assert any("حد ضرر" in w for w in r.warnings_fa)  # ...and the user is told
    assert any("خرید" in line for line in r.description_fa)


def test_usdt_quote_stop_loss_and_rsi() -> None:
    r = parse_rules("اگر RSI اتریوم زیر 25 رفت با 20 درصد سرمایه تتری بخر، حد ضرر 4 درصد، 6% سود")
    assert r.spec is not None, r.error_fa
    assert r.spec.symbol == "ETHUSDT"
    assert r.spec.entry[0].kind == "rsi_below" and r.spec.entry[0].value == 25
    assert r.spec.stop_loss_pct == 4 and r.spec.take_profit_pct == 6 and r.spec.position_size_pct == 20


def test_lookback_in_days_on_4h() -> None:
    r = parse_rules("روی چارت ۴ ساعته اگر بیتکوین در ۳ روز ۱۰٪ افت کرد بخر")
    assert r.spec is not None
    assert r.spec.resolution == "4h" and r.spec.entry[0].lookback == 18


def test_unknown_input_gives_persian_error() -> None:
    r = parse_rules("سلام خوبی؟")
    assert r.spec is None and r.error_fa


def test_default_symbol_used() -> None:
    r = parse_rules("وقتی ۳٪ ریخت بخر", default_symbol="ETHTMN")
    assert r.spec is not None and r.spec.symbol == "ETHTMN"


def test_mock_llm_path_uses_rules() -> None:
    r = asyncio.run(build_strategy(MockLLM(), "وقتی بیت‌کوین ۵٪ ریخت بخر"))
    assert r.spec is not None and r.source == "rules"


class BadLLM:
    name = "bad"

    async def chat(self, system: str, user: str, json_mode: bool = False) -> str | None:
        return '{"symbol": "DOGEUSDT", "entry": []}'  # invalid on purpose


class GoodLLM:
    name = "good"

    async def chat(self, system: str, user: str, json_mode: bool = False) -> str | None:
        return (
            '{"symbol": "BTCUSDT", "resolution": "1h", "entry": [{"kind": "rsi_below", "value": 30}],'
            ' "position_size_pct": 15, "take_profit_pct": 4}'
        )


def test_invalid_llm_json_falls_back() -> None:
    r = asyncio.run(build_strategy(BadLLM(), "وقتی بیت‌کوین ۵٪ ریخت بخر"))
    assert r.spec is not None and r.source == "rules"
    assert "معتبر نبود" in r.warnings_fa[0]


def test_valid_llm_json_gets_stop_loss() -> None:
    r = asyncio.run(build_strategy(GoodLLM(), "..."))
    assert r.source == "good" and r.spec is not None and r.spec.stop_loss_pct == 5


def test_spec_validation_rejects_nonsense() -> None:
    with pytest.raises(ValueError):
        StrategySpec.model_validate(
            {"symbol": "BTCTMN", "entry": [{"kind": "ema_cross_up", "fast": 30, "slow": 10}]}
        )
    with pytest.raises(ValueError):
        StrategySpec.model_validate({"symbol": "BTCTMN", "entry": [{"kind": "drop_from_high"}]})
    with pytest.raises(ValueError):
        StrategySpec.model_validate(
            {"symbol": "BTCTMN", "entry": [{"kind": "rsi_below", "value": 20}], "position_size_pct": 150}
        )


def test_shock_reversal_sentence() -> None:
    """The user's idea: a >10% move within 30 minutes -> trade against it, 1% target (spot: buy the dump)."""
    text = "هر وقت ارزی زیر ۳۰ دقیقه بیشتر از ۱۰ درصد قیمتش جابجا شد در جهت مخالفش وارد ترید شو و تارگتت ۱ درصد باشه"
    r = parse_rules(text, default_symbol="BTCTMN")
    assert r.spec is not None, r.error_fa
    s = r.spec
    assert s.resolution == "5m" and s.take_profit_pct == 1 and s.stop_loss_pct == 5
    c = s.entry[0]
    assert c.kind == "drop_from_high" and c.pct == 10 and c.minutes == 30 and c.lookback == 6
    assert any("شورت" in w for w in r.warnings_fa)  # the impossible side is spelled out
    assert any("همهٔ بازارها" in w for w in r.warnings_fa)
    assert "۳۰ دقیقه" in r.description_fa[1]


def test_minutes_window_becomes_candles() -> None:
    def spec(res: str, minutes: int) -> StrategySpec:
        return StrategySpec.model_validate(
            {
                "symbol": "SOLTMN",
                "resolution": res,
                "entry": [{"kind": "drop_from_high", "pct": 4, "minutes": minutes}],
            }
        )

    assert spec("15m", 30).entry[0].lookback == 2
    assert spec("1h", 1440).entry[0].lookback == 24
    with pytest.raises(ValueError):
        spec("1h", 30)  # a window shorter than one candle
    with pytest.raises(ValueError):
        StrategySpec.model_validate({"symbol": "not-a-market", "entry": [{"kind": "rsi_below", "value": 20}]})
