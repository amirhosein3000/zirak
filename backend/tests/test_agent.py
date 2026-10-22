"""The challenge agent (zirak/agent): features, labels, model, posture, guard, sizing, backtest, restart."""

import asyncio
import json
import math
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from zirak.agent.config import AgentConfig
from zirak.agent.engine import Agent, PendingEntry
from zirak.agent.features import FEATURES, feature_frame
from zirak.agent.journal import Journal
from zirak.agent.labeling import Costs, triple_barrier
from zirak.agent.model import MetaModel
from zirak.agent.posture import Posture, PostureAgent, parse_posture, rule_posture
from zirak.agent.runner import reconcile, run_backtest, train_model
from zirak.config import SAMPLE_DATA_DIR, Settings
from zirak.data.source import add_derived
from zirak.data.store import load_candle_dir
from zirak.engine.bot import SimClock
from zirak.exchange.paper import PaperExchange
from zirak.exchange.replay import ReplayExchange
from zirak.fees import FeeModel
from zirak.markets import DEFAULT_MARKETS
from zirak.models import Candle, OrderRequest, OrderType, Side

T0 = datetime(2026, 1, 1, tzinfo=UTC)
COSTS = Costs(taker=0.0025, maker=0.002, slippage=0.0005)


def sample_series() -> dict[str, list[Candle]]:
    raw = load_candle_dir(SAMPLE_DATA_DIR)
    add_derived(raw)
    return {sym: cs for (sym, res), cs in raw.items() if res == "1h"}


def bars(rows: Sequence[Sequence[float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


# ---- features --------------------------------------------------------------------------------------
def test_features_are_causal() -> None:
    """Row i computed from candles[:i+1] equals row i computed from the full series: no look-ahead."""
    cs = sample_series()["BTCTMN"][:600]
    full = feature_frame(cs)
    for k in (250, 400, 599):
        part = feature_frame(cs[: k + 1])
        for f in FEATURES:
            a, b = float(part[f].iloc[-1]), float(full[f].iloc[k])
            assert (math.isnan(a) and math.isnan(b)) or a == pytest.approx(b, rel=1e-9, abs=1e-12), f


def test_cross_rate_features() -> None:
    s = sample_series()
    from zirak.agent.features import implied_closes

    imp = implied_closes(s, "BTCTMN")
    assert imp is not None and len(imp) > 100
    df = feature_frame(s["BTCTMN"], imp)
    assert df["basis_pct"].notna().sum() > 100
    assert implied_closes(s, "USDTTMN") is None and implied_closes(s, "BTCUSDT") is None


# ---- triple-barrier labels ---------------------------------------------------------------------------
def test_triple_barrier_cases() -> None:
    zero = Costs(0, 0, 0)
    # TP first (high trades through 102)
    out = triple_barrier(
        bars([(100, 100, 100, 100), (100, 101, 99.5, 100.5), (100.5, 102.5, 100, 102)]), 0, 2, 2, 5, zero
    )
    assert out is None  # not enough future bars for max_bars=5
    df = bars(
        [(100, 100, 100, 100), (100, 101, 99.5, 100.5), (100.5, 102.5, 100, 102), (102, 102, 101, 101)]
        + [(101, 101, 101, 101)] * 4
    )
    out = triple_barrier(df, 0, 2, 2, 5, zero)
    assert out is not None and out.exit_kind == "tp" and out.net_ret_pct == pytest.approx(2.0)
    # both barriers inside one candle -> the stop is assumed first (pessimistic)
    df = bars([(100, 100, 100, 100), (100, 103, 97, 100)] + [(100, 100, 100, 100)] * 6)
    out = triple_barrier(df, 0, 2, 2, 5, zero)
    assert out is not None and out.exit_kind == "sl" and out.net_ret_pct == pytest.approx(-2.0)
    # a gap through the stop fills at the (worse) open
    df = bars([(100, 100, 100, 100), (100, 100, 99, 99.5), (95, 96, 94, 95)] + [(95, 95, 95, 95)] * 6)
    out = triple_barrier(df, 0, 2, 2, 5, zero)
    assert out is not None and out.exit_kind == "sl" and out.net_ret_pct == pytest.approx(-5.0)
    # time exit at the close of the last bar, with costs
    df = bars([(100, 100, 100, 100)] + [(100, 100.5, 99.5, 100.2)] * 7)
    out = triple_barrier(df, 0, 2, 2, 3, COSTS)
    assert out is not None and out.exit_kind == "time" and out.bars == 3 and out.net_ret_pct < 0.2


# ---- model -------------------------------------------------------------------------------------------
def _toy_rows(n: int, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    x = rng.normal(size=n)
    label = (x + rng.normal(scale=0.7, size=n) > 0).astype(int)
    df = pd.DataFrame({f: rng.normal(size=n) for f in FEATURES})
    df["rsi_14"] = x  # one informative feature
    df["setup"] = "mean_reversion"
    df["tp_pct"], df["sl_pct"] = 2.0, 2.0
    df["label"] = label
    df["net_ret_pct"] = np.where(label == 1, 1.5, -2.5)
    df["ts"] = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    df["symbol"] = "BTCTMN"
    return df


def test_model_learns_is_deterministic_and_round_trips(tmp_path: Path) -> None:
    rows = _toy_rows(800)
    a, b = MetaModel(), MetaModel()
    ca, cb = a.fit(rows, 0.5), b.fit(rows, 0.5)
    assert ca.model_id == cb.model_id and ca.kind == "gbm"
    assert ca.holdout_auc is not None and ca.holdout_auc > 0.7
    f = {k: 0.0 for k in FEATURES}
    hi, lo = (
        a.decide({**f, "rsi_14": 2.0}, "mean_reversion", 2, 2, 0.5),
        a.decide({**f, "rsi_14": -2.0}, "mean_reversion", 2, 2, 0.5),
    )
    assert hi.prob > 0.6 > lo.prob and hi.take and not lo.take
    a.save(tmp_path / "m")
    c = MetaModel.load(tmp_path / "m")
    assert c.card.model_id == ca.model_id
    assert c.decide({**f, "rsi_14": 2.0}, "mean_reversion", 2, 2, 0.5).prob == hi.prob


def test_model_falls_back_to_smoothed_win_rates() -> None:
    m = MetaModel()
    card = m.fit(_toy_rows(30), 0.5)
    assert card.kind == "prior" and "fewer than" in card.notes
    v = m.decide({k: 0.0 for k in FEATURES}, "breakout", 3, 1.5, 0.5)
    assert v.source == "prior" and 0 < v.prob < 1


def test_ev_and_kelly_maths() -> None:
    m = MetaModel(min_prob=0.5, min_ev_pct=0.05, kelly_ref=0.25)
    ev, kelly = m._ev(0.6, 2.0, 2.0, 0.5)  # win 1.5, lose 2.5
    assert ev == pytest.approx(0.6 * 1.5 - 0.4 * 2.5)
    assert kelly == pytest.approx(0.6 - 0.4 / (1.5 / 2.5))


# ---- posture -----------------------------------------------------------------------------------------
def test_parse_posture_clamps_and_drops_unknowns() -> None:
    text = json.dumps(
        {
            "markets": {
                "BTCTMN": {
                    "stance": "normal",
                    "risk_multiplier": 9,
                    "allowed_setups": ["breakout", "hack"],
                    "reason_fa": "x",
                },
                "ETHTMN": {"stance": "avoid", "risk_multiplier": 1.2, "allowed_setups": ["breakout"]},
                "DOGETMN": {"stance": "normal"},
            },
            "summary_fa": "s",
        }
    )
    parsed = parse_posture("```json\n" + text + "\n```", ["BTCTMN", "ETHTMN"])
    assert parsed is not None
    m, summary = parsed
    assert m["BTCTMN"].risk_multiplier == 1.5 and m["BTCTMN"].allowed_setups == ["breakout"]
    assert m["ETHTMN"].risk_multiplier == 0 and not m["ETHTMN"].allows("breakout")
    assert "DOGETMN" not in m and summary == "s"
    assert parse_posture("not json", ["BTCTMN"]) is None


class FakeLLM:
    name = "fake"
    model = "fake-1"

    def __init__(self, final: str) -> None:
        self.final, self.turn = final, 0

    async def chat(self, system: str, user: str, json_mode: bool = False) -> str | None:
        return None

    async def chat_tools(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        self.turn += 1
        if self.turn == 1:
            return {
                "content": None,
                "tool_calls": [
                    {
                        "id": "c1",
                        "function": {"name": "get_market_snapshot", "arguments": '{"symbol": "BTCTMN"}'},
                    }
                ],
            }
        assert messages[-1]["role"] == "tool" and "rsi" in messages[-1]["content"]
        return {"content": self.final}


def test_posture_agent_uses_tools_then_decides() -> None:
    async def snap(args: dict[str, Any]) -> dict[str, Any]:
        return {"symbol": args["symbol"], "rsi": 30}

    final = json.dumps(
        {
            "markets": {
                "BTCTMN": {
                    "stance": "cautious",
                    "risk_multiplier": 0.5,
                    "allowed_setups": ["mean_reversion"],
                    "reason_fa": "ریزش",
                }
            },
            "summary_fa": "محتاط",
        }
    )
    agent = PostureAgent(FakeLLM(final), {"get_market_snapshot": snap}, ["BTCTMN", "ETHTMN"])
    frames = {s: feature_frame(sample_series()[s][:400]) for s in ("BTCTMN", "ETHTMN")}
    p = asyncio.run(agent.decide(T0, frames))
    assert p.source == "llm:fake-1" and p.tool_calls == [
        {"name": "get_market_snapshot", "args": {"symbol": "BTCTMN"}}
    ]
    assert p.for_market("BTCTMN").risk_multiplier == 0.5
    assert "ETHTMN" in p.markets  # forgotten market keeps the rule posture
    bad = asyncio.run(
        PostureAgent(FakeLLM("oops"), {"get_market_snapshot": snap}, ["BTCTMN"]).decide(T0, frames)
    )
    assert bad.source == "rules" and "قواعد" in bad.summary_fa


def test_rule_posture_and_round_trip() -> None:
    frames = {"BTCTMN": feature_frame(sample_series()["BTCTMN"][:500])}
    p = rule_posture(T0, frames)
    assert p.source == "rules" and "BTCTMN" in p.markets
    assert Posture.from_dict(json.loads(json.dumps(p.to_dict()))).for_market("BTCTMN") == p.for_market(
        "BTCTMN"
    )


# ---- engine: guard, sizing -------------------------------------------------------------------------
def make_agent(
    tmp_path: Path, cfg: AgentConfig | None = None, package: dict[str, Any] | None = None
) -> tuple[Agent, PaperExchange, SimClock]:
    cfg = cfg or AgentConfig.model_validate({})
    markets = {s: DEFAULT_MARKETS[s] for s in cfg.all_markets}
    clock = SimClock(T0)
    replay = ReplayExchange({}, markets=markets)
    paper = PaperExchange(
        replay,
        {s: markets[s] for s in cfg.markets},
        FeeModel(D("0.002"), D("0.0025")),
        D("5"),
        {"TMN": D("5000000")},
        D("1"),
        clock,
    )
    agent = Agent(cfg, paper, markets, MetaModel(), Journal(tmp_path / "run"), COSTS, clock, package=package)
    return agent, paper, clock


def test_guard_states(tmp_path: Path) -> None:
    agent, _, _ = make_agent(tmp_path)
    assert agent.check_guard(T0, D("5000000")) == "ok"
    assert agent.check_guard(T0, D("4870000")).startswith("pause:daily loss")  # -2.6 % today
    agent.guard.day_start = D("4800000")
    assert agent.check_guard(T0, D("4740000")).startswith("pause:drawdown")  # -5.2 % from peak
    assert agent.check_guard(T0, D("4590000")).startswith("kill:drawdown")  # -8.2 %
    agent2, _, _ = make_agent(
        tmp_path / "b", package={"start_balance": "5000000", "liquidity_limit": "4700000"}
    )
    assert agent2.check_guard(T0, D("4850000")).startswith("pause:liquidation")  # 50 % of the cushion left
    assert agent2.check_guard(T0, D("4780000")).startswith("kill:liquidation")  # 27 % left
    end = T0 + timedelta(hours=10)
    cfg = AgentConfig.model_validate({"clock": {"end": end.isoformat()}})
    agent3, _, _ = make_agent(tmp_path / "c", cfg)
    assert agent3.check_guard(end - timedelta(hours=3), D("5000000")) == "pause:challenge end near"
    assert agent3.check_guard(end - timedelta(minutes=60), D("5000000")) == "flatten:challenge end"
    assert agent3.check_guard(end - timedelta(minutes=10), D("5000000")) == "flatten_hard:challenge end"


def test_sizing_respects_every_cap(tmp_path: Path) -> None:
    from zirak.agent.setups import Candidate

    agent, _, _ = make_agent(tmp_path)
    agent.last_price["BTCTMN"] = D("10000000000")
    cand = Candidate("BTCTMN", "mean_reversion", T0, 0, 1e10, 2.0, 0.6, 16, "")
    big = agent.size("BTCTMN", D("5000000"), D("5000000"), D("0"), cand, D("1"))
    assert big["bound_by"] == "max_position" and D(big["value_tmn"]) <= D("1500000")  # 30 %: never all in
    room = agent.size("BTCTMN", D("5000000"), D("5000000"), D("3200000"), cand, D("1"))
    assert room["bound_by"] == "exposure_room" and D(room["value_tmn"]) <= D("300000")
    cash = agent.size("BTCTMN", D("5000000"), D("200000"), D("0"), cand, D("1"))
    assert cash["bound_by"] == "free_cash"
    tiny = agent.size("BTCTMN", D("5000000"), D("5000000"), D("0"), cand, D("0.001"))
    assert tiny["qty"] == "0" and "حداقل" in tiny["why_fa"]


# ---- backtest --------------------------------------------------------------------------------------
def test_backtest_runs_logs_every_decision_and_is_reproducible(tmp_path: Path) -> None:
    series = sample_series()
    cfg = AgentConfig.model_validate({"model": {"retrain_hours": 240}})
    settings = Settings(data_dir=tmp_path, kill_file=tmp_path / "KILL")
    markets = {s: DEFAULT_MARKETS[s] for s in series}
    r1 = asyncio.run(run_backtest(cfg, series, markets, settings, tmp_path / "a"))
    r2 = asyncio.run(run_backtest(cfg, series, markets, settings, tmp_path / "b"))
    assert r1["ai"]["candidates"] > 0 and r1["period"]["bars"] > 100

    def strip(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{k: v for k, v in d.items() if k != "model"} for d in rows]

    da, db = Journal(tmp_path / "a").read("decisions.jsonl"), Journal(tmp_path / "b").read("decisions.jsonl")
    assert strip(da) == strip(db), "same data + config must give the same decisions"
    assert {k: r1[k] for k in ("return_pct", "trades", "max_drawdown_pct")} == {
        k: r2[k] for k in ("return_pct", "trades", "max_drawdown_pct")
    }
    for d in da:
        if d["kind"] == "candidate":
            assert d["action"] in ("buy", "skip") and d["reason_fa"] and "prob" in d["model"]
    manifest = json.loads((tmp_path / "a" / "manifest.json").read_text())
    assert manifest["mode"] == "backtest" and manifest["walk_forward"] is True


def test_backtest_flattens_before_the_challenge_end(tmp_path: Path) -> None:
    series = sample_series()
    ts = series["BTCTMN"][-1].ts
    cfg = AgentConfig.model_validate(
        {
            "clock": {
                "end": (ts - timedelta(hours=1)).isoformat(),
                "no_entry_before_end_h": 4,
                "flatten_before_end_min": 180,
                "hard_flatten_before_end_min": 60,
            },
            "risk": {"risk_per_trade_pct": 2.0},
            "model": {"min_prob": 0.0, "min_ev_pct": -1.0, "retrain_hours": 1000},
        }
    )
    settings = Settings(data_dir=tmp_path, kill_file=tmp_path / "KILL")
    markets = {s: DEFAULT_MARKETS[s] for s in series}
    r = asyncio.run(
        run_backtest(
            cfg,
            series,
            markets,
            settings,
            tmp_path / "f",
            walk_forward=False,
            model=MetaModel(min_prob=0.0, min_ev_pct=-5.0, kelly_ref=0.01),
        )
    )
    assert r["trades"] > 0, "the permissive model should have traded"
    assert r["open_positions_at_end"] == 0, "everything must be Toman again at the end"
    statuses = [d["status"] for d in Journal(tmp_path / "f").read("decisions.jsonl") if d["kind"] == "guard"]
    assert any(s.startswith("flatten") for s in statuses)


def test_train_model_uses_only_the_past() -> None:
    series = sample_series()
    cfg = AgentConfig.model_validate({})
    until = series["BTCTMN"][900].ts
    m = train_model(cfg, series, COSTS, until)
    assert m.card.last_ts is None or pd.Timestamp(m.card.last_ts) < until


# ---- restart -----------------------------------------------------------------------------------------
def test_state_survives_restart_and_reconcile_cancels_strangers(tmp_path: Path) -> None:
    agent, paper, clock = make_agent(tmp_path)
    paper.set_last_price("BTCTMN", D("10000000000"))
    stranger = asyncio.run(
        paper.place_order(OrderRequest("BTCTMN", Side.BUY, OrderType.LIMIT, D("0.0001"), D("9000000000")))
    )
    mine = asyncio.run(
        paper.place_order(OrderRequest("BTCTMN", Side.BUY, OrderType.LIMIT, D("0.0001"), D("9100000000")))
    )
    agent.pending["BTCTMN"] = PendingEntry(
        "BTCTMN", "mean_reversion", "D000001", mine.id, T0.isoformat(), 2, 1, 16
    )
    agent._save()
    again = Agent(agent.cfg, paper, agent.markets, MetaModel(), Journal(tmp_path / "run"), COSTS, clock)
    again.restore(again.journal.load_state() or {})
    assert again.pending["BTCTMN"].order_id == mine.id
    asyncio.run(reconcile(again))
    assert not stranger.status.is_open and mine.status.is_open
    kinds = [d["kind"] for d in again.journal.read("decisions.jsonl")]
    assert "reconcile" in kinds


def test_reconcile_adopts_unmanaged_coins(tmp_path: Path) -> None:
    from zirak.models import BookLevel, OrderBook

    agent, paper, _ = make_agent(tmp_path)
    paper._free["ETH"] = D("0.01")

    async def book(symbol: str) -> OrderBook:
        return OrderBook(symbol, T0, [BookLevel(D("400000000"), D("1"))], [BookLevel(D("400100000"), D("1"))])

    paper.get_order_book = book  # type: ignore[method-assign]
    asyncio.run(reconcile(agent))
    pos = agent.positions["ETHTMN"]
    assert pos.setup == "adopted" and pos.stop < D("400000000") < pos.take_profit


def test_config_rejects_coin_quoted_markets_and_unknown_setups() -> None:
    with pytest.raises(ValueError):
        AgentConfig.model_validate({"markets": ["BTCUSDT"]})
    with pytest.raises(ValueError):
        AgentConfig.model_validate({"setups": ["yolo"]})
    assert replace(Costs(0.0025, 0.002, 0.0005)).round_trip_pct() == pytest.approx(0.6)


# ---- shadow mode, verify, export, MCP --------------------------------------------------------------
class FakeWallexData(ReplayExchange):
    """Serves the sample candles as if live: every call releases one more closed candle."""

    def __init__(self) -> None:
        raw = load_candle_dir(SAMPLE_DATA_DIR)
        add_derived(raw)
        super().__init__(raw, markets=dict(DEFAULT_MARKETS))
        self.released = 700

    async def get_candles(
        self, symbol: str, resolution: str, start: Any = None, end: Any = None
    ) -> list[Candle]:
        if symbol == "BTCTMN":
            self.released += 1
        return self.series(symbol, resolution)[: self.released]


def test_shadow_run_trades_on_new_bars_journals_and_resumes(tmp_path: Path) -> None:
    from zirak.agent.runner import run_live

    settings = Settings(data_dir=tmp_path, kill_file=tmp_path / "KILL")
    cfg = AgentConfig.model_validate({"execution": {"poll_s": 1}})
    data = FakeWallexData()
    report = asyncio.run(
        run_live(cfg, settings, tmp_path / "shadow", "shadow", data, MetaModel(), stop_after_s=2.5)
    )
    assert report["mode"] == "shadow" and report["period"]["bars"] >= 2
    bars_log = Journal(tmp_path / "shadow").read("bars.jsonl")
    assert bars_log and "latency_ms" in bars_log[0]
    manifest = json.loads((tmp_path / "shadow" / "manifest.json").read_text())
    assert manifest["mode"] == "shadow" and manifest["resumed"] is False
    asyncio.run(run_live(cfg, settings, tmp_path / "shadow", "shadow", data, MetaModel(), stop_after_s=1.2))
    assert json.loads((tmp_path / "shadow" / "manifest.json").read_text())["resumed"] is True


def test_kill_file_stops_a_shadow_run(tmp_path: Path) -> None:
    from zirak.agent.runner import run_live

    settings = Settings(data_dir=tmp_path, kill_file=tmp_path / "KILL")
    settings.kill_file.write_text("x")
    cfg = AgentConfig.model_validate({"execution": {"poll_s": 1}})
    asyncio.run(
        run_live(cfg, settings, tmp_path / "k", "shadow", FakeWallexData(), MetaModel(), stop_after_s=30)
    )
    kinds = [d["kind"] for d in Journal(tmp_path / "k").read("decisions.jsonl")]
    assert "kill" in kinds


def test_verify_export_and_report_cli(tmp_path: Path) -> None:
    from zirak.agent.verify import verify_run
    from zirak.cli import main

    series = sample_series()
    settings = Settings(data_dir=tmp_path, kill_file=tmp_path / "KILL")
    cfg = AgentConfig.model_validate({"model": {"retrain_hours": 240}})
    asyncio.run(run_backtest(cfg, series, {s: DEFAULT_MARKETS[s] for s in series}, settings, tmp_path / "v"))
    result = verify_run(tmp_path / "v")
    assert result["ok"] and result["reproduced_pct"] == 100.0 and result["models_used"]
    # tampering with a logged probability is caught
    path = tmp_path / "v" / "decisions.jsonl"
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    first = next(r for r in rows if r["kind"] == "candidate")
    first["model"]["prob"] = 0.99
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    assert not verify_run(tmp_path / "v")["ok"]
    assert main(["agent", "export", str(tmp_path / "v")]) == 0
    assert (tmp_path / "v" / "decisions.csv").read_text(encoding="utf-8-sig").startswith("id,ts,kind")
    assert main(["agent", "report", str(tmp_path / "v")]) == 0
    assert "realised" in (tmp_path / "v" / "report.md").read_text(encoding="utf-8")


def test_mcp_server_is_read_only(tmp_path: Path) -> None:
    from zirak.agent.mcp_server import build_server

    settings = Settings(data_dir=tmp_path, kill_file=tmp_path / "KILL", replay_dir=SAMPLE_DATA_DIR)
    series = sample_series()
    cfg = AgentConfig.model_validate({"model": {"retrain_hours": 240}})
    asyncio.run(
        run_backtest(cfg, series, {s: DEFAULT_MARKETS[s] for s in series}, settings, tmp_path / "runs" / "r1")
    )
    server = build_server(settings)
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {
        "market_snapshot",
        "list_runs",
        "run_report",
        "recent_decisions",
        "explain_decision",
        "verify",
        "model_card",
    }
    assert not any(w in n for n in names for w in ("order", "buy", "sell", "cancel", "withdraw", "transfer"))
    runs = asyncio.run(server.call_tool("list_runs", {}))
    assert "r1" in json.dumps(
        [getattr(c, "text", "") for c in runs[0]] if isinstance(runs, tuple) else str(runs)
    )
    snap = asyncio.run(server.call_tool("market_snapshot", {"symbol": "BTCTMN"}))
    assert "rsi_14" in str(snap)


def test_unfilled_exit_is_repriced_after_its_ttl(tmp_path: Path) -> None:
    from zirak.agent.engine import EXIT_TTL_S, Position

    agent, paper, clock = make_agent(tmp_path)
    paper._free["BTC"] = D("0.001")
    paper.set_last_price("BTCTMN", D("10000000000"))
    agent.last_price["BTCTMN"] = D("10000000000")
    pos = Position(
        "BTCTMN",
        "mean_reversion",
        "D1",
        D("0.001"),
        D("10000000"),
        D("10000000000"),
        D("9800000000"),
        D("10300000000"),
        T0.isoformat(),
        16,
    )
    agent.positions["BTCTMN"] = pos
    asyncio.run(agent.exit_position(pos, "stop_loss", T0))
    first = pos.exit_order_id
    assert first is not None
    clock.now = T0 + timedelta(seconds=EXIT_TTL_S + 1)
    asyncio.run(agent.on_tick(clock.now))
    assert pos.exit_order_id not in (None, first), "a stale exit must be canceled and sent again"
    assert not asyncio.run(paper.get_order("BTCTMN", first)).status.is_open
