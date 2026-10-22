"""Crash drill: synthetic scenarios after real candles, played through the normal backtester."""

import itertools
from decimal import Decimal as D
from pathlib import Path

from fastapi.testclient import TestClient

from tests.conftest import flat_candles
from zirak.api.main import create_app
from zirak.backtest.drill import SCENARIOS, build_path
from zirak.config import SAMPLE_DATA_DIR, Settings
from zirak.markets import DEFAULT_MARKETS


def test_paths_are_deterministic_and_follow_the_legs() -> None:
    m = DEFAULT_MARKETS["BTCTMN"]
    history = flat_candles(200, price="1000000000", volume="5")
    for sc in SCENARIOS.values():
        a, b = build_path(history, sc, m, "1h"), build_path(history, sc, m, "1h")
        assert a == b, "a drill must always play the same way"
        assert len(a) == sum(n for n, _ in sc.legs)
        assert a[0].ts > history[-1].ts and all(x.ts < y.ts for x, y in itertools.pairwise(a))
        assert all(c.low <= min(c.open, c.close) and c.high >= max(c.open, c.close) for c in a)
        assert all(c.volume == D("5") for c in a)
    crash = build_path(history, SCENARIOS["flash_crash"], m, "1h")
    assert float(min(c.close for c in crash)) < 1e9 * 0.8  # a real crash: more than -20 %


def test_gap_opens_below_the_previous_close() -> None:
    m = DEFAULT_MARKETS["BTCTMN"]
    sc = SCENARIOS["gap_down"]
    path = build_path(flat_candles(200, price="1000000000"), sc, m, "1h")
    gap_at = sc.legs[0][0]
    before, gap = path[gap_at - 1], path[gap_at]
    assert gap.open < before.close * D("0.85")  # the stop can't fill at its price: it gapped through


def test_drill_api_plays_every_scenario(tmp_path: Path) -> None:
    s = Settings(
        data_dir=tmp_path, db_path=tmp_path / "x.sqlite", kill_file=tmp_path / "K", replay_dir=SAMPLE_DATA_DIR
    )
    with TestClient(create_app(s)) as c:
        scenarios = c.get("/api/drill/scenarios").json()
        assert {x["key"] for x in scenarios} == set(SCENARIOS)
        for sc in SCENARIOS:
            r = c.post(
                "/api/drill",
                json={
                    "strategy": "dca",
                    "params": {"every": 4, "size_pct": 10},
                    "symbol": "BTCTMN",
                    "scenario": sc,
                },
            ).json()
            n = len(r["x"])
            assert n == len(r["price"]) and all(len(v) == n for v in r["lines"].values())
            assert 0 < r["start_index"] < n and r["bottom_pct"] < 0
            assert {x["key"] for x in r["results"]} == {"zirak", "naked", "emotional", "hold"}
            assert r["events"][0]["kind"] == "start" or r["events"][0]["i"] <= r["start_index"]
            assert all(0 <= e["i"] < n for e in r["events"])
            assert "ساختگی" in r["note_fa"] and r["headline_fa"]
        assert c.post("/api/drill", json={"strategy": "dca", "scenario": "nope"}).status_code == 422


def test_lines_are_100_when_the_drill_starts(tmp_path: Path) -> None:
    s = Settings(
        data_dir=tmp_path, db_path=tmp_path / "x.sqlite", kill_file=tmp_path / "K", replay_dir=SAMPLE_DATA_DIR
    )
    with TestClient(create_app(s)) as c:
        r = c.post("/api/drill", json={"strategy": "dca", "symbol": "ETHTMN", "scenario": "pump_dump"}).json()
        i = r["start_index"]
        assert all(v[i] == 100 for v in r["lines"].values())
        hold = next(x for x in r["results"] if x["key"] == "hold")
        assert abs(r["lines"]["hold"][-1] - 100 - hold["return_pct"]) < 0.05  # scoreboard == final result


def test_outcome_words() -> None:
    from zirak.backtest.drill import outcome

    assert (outcome(-0.44) == "۰٫۴٪ زیان" and outcome(1.25) == "۱٫۲٪ سود") or outcome(1.25) == "۱٫۳٪ سود"
    assert outcome(0.01) == "تقریباً بدون تغییر"
