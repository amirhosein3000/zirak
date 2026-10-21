"""Command line: `zirak <command>`. Run `zirak -h` for the list."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from zirak.config import SAMPLE_DATA_DIR, load_settings


def _json_arg(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    p = Path(raw)
    text = p.read_text(encoding="utf-8") if p.exists() else raw
    data: dict[str, Any] = json.loads(text)
    return data


def cmd_make_sample(args: argparse.Namespace) -> int:
    from zirak.data.synthetic import generate

    out = Path(args.out)
    paths = generate(out)
    print(f"wrote {len(paths)} SYNTHETIC candle files to {out}")
    return 0


def _strategy_from_args(args: argparse.Namespace) -> tuple[Any, Any, str, str]:
    from zirak.engine.risk import RiskConfig
    from zirak.strategy.registry import build_strategy
    from zirak.strategy.spec import RuleStrategy, StrategySpec

    risk = _json_arg(args.risk)
    if args.spec:
        spec = StrategySpec.model_validate(_json_arg(args.spec))
        cfg = RiskConfig.from_dict(
            {
                "stop_loss_pct": spec.stop_loss_pct,
                "take_profit_pct": spec.take_profit_pct,
                "cooldown_candles": spec.cooldown_candles,
                **risk,
            }
        )
        return RuleStrategy(spec), cfg, spec.symbol, spec.resolution
    return (
        build_strategy(args.strategy, _json_arg(args.params)),
        RiskConfig.from_dict(risk),
        args.symbol,
        args.resolution,
    )


def cmd_backtest(args: argparse.Namespace) -> int:
    from zirak.backtest.engine import BacktestSetup, run_backtest, save_report
    from zirak.data.source import build_replay, load_series
    from zirak.fees import FeeModel

    s = load_settings()
    strat, risk, symbol, resolution = _strategy_from_args(args)
    replay, label = build_replay(s)
    market = replay.markets[symbol]
    series = load_series(replay, symbol, resolution)
    initial = (
        Decimal(args.initial)
        if args.initial
        else (s.paper_start_tmn if market.quote == "TMN" else s.paper_start_usdt)
    )
    setup = BacktestSetup(
        market,
        resolution,
        strat,
        risk,
        FeeModel(s.fee_maker, s.fee_taker),
        s.slippage_bps,
        initial,
        s.fill_participation,
        meta={"data": label},
    )
    report = run_backtest(series, setup)
    path = save_report(report, Path(args.out) if args.out else s.data_dir / "reports")
    m = report["metrics"]
    print(f"{symbol} {resolution} {strat.key} on {label} data ({len(series)} candles)")
    for k in (
        "return_pct",
        "buy_hold_return_pct",
        "max_drawdown_pct",
        "buy_hold_max_drawdown_pct",
        "sharpe",
        "win_rate_pct",
        "trades",
        "orders",
        "exposure_pct",
        "fees_paid_quote",
    ):
        print(f"  {k:28s} {m[k]}")
    print(f"report: {path}")
    return 0


def cmd_paper(args: argparse.Namespace) -> int:
    from zirak.data.source import build_replay
    from zirak.engine.runner import BotRunner

    s = load_settings()
    strat, risk, symbol, resolution = _strategy_from_args(args)
    replay, label = build_replay(s)
    runner = BotRunner(s, replay)

    async def run() -> None:
        await runner.start(strat, risk, symbol, resolution, speed_s=args.speed)
        print(
            f"paper bot started: {strat.key} on {symbol} {resolution} ({label} replay). "
            "Stop with Ctrl+C or `zirak kill`."
        )
        last = 0
        while runner.running:
            await asyncio.sleep(max(args.speed, 0.5))
            st = await runner.status(log_limit=5)
            bot = st["bot"]
            if bot and len(runner.bot.log if runner.bot else []) != last:
                last = len(runner.bot.log) if runner.bot else 0
                e = st["log"][0]
                print(
                    f"[{e['ts']}] {e['side']} {e['reason']} approved={e['decision']['approved']} "
                    f"equity={bot['equity']}"
                )
        st = await runner.status()
        print("finished:", {k: st["bot"][k] for k in ("equity", "pnl_pct", "killed")} if st["bot"] else st)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("interrupted")
    return 0


def cmd_kill(args: argparse.Namespace) -> int:
    import httpx

    s = load_settings()
    s.kill_file.parent.mkdir(parents=True, exist_ok=True)
    s.kill_file.write_text("cli kill\n", encoding="utf-8")
    print(f"KILL file written: {s.kill_file} (every running bot stops at its next step)")
    try:
        r = httpx.post(f"{args.api}/api/kill", timeout=5)
        print(f"API kill: HTTP {r.status_code}, canceled orders: {r.json().get('canceled_orders')}")
    except httpx.HTTPError as e:
        print(f"API not reachable ({type(e).__name__}); the KILL file still stops bots.")
    return 0


def cmd_reset_kill(args: argparse.Namespace) -> int:
    s = load_settings()
    s.kill_file.unlink(missing_ok=True)
    print("kill switch reset")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("zirak.api.main:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def cmd_blocked(args: argparse.Namespace) -> int:
    print(
        "BLOCKED: the Wallex recorder/backfill needs docs/wallex-api/ (not in the repo yet). "
        "No endpoints are written from memory. See docs/progress.md.",
        file=sys.stderr,
    )
    return 2


def cmd_data_stats(args: argparse.Namespace) -> int:
    from zirak.data.source import build_replay

    replay, label = build_replay(load_settings())
    print(f"data: {label}")
    for symbol, res, n in replay.available():
        series = replay.series(symbol, res)
        print(f"  {symbol:8s} {res:4s} {n:6d} candles  {series[0].ts:%Y-%m-%d} -> {series[-1].ts:%Y-%m-%d}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="zirak", description="Zirak smart trader")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("make-sample", help="write the deterministic SYNTHETIC sample dataset")
    sp.add_argument("--out", default=str(SAMPLE_DATA_DIR))
    sp.set_defaults(fn=cmd_make_sample)

    for name, fn, hlp in (
        ("backtest", cmd_backtest, "run a backtest and save a JSON report"),
        ("paper", cmd_paper, "run a paper bot on replayed data (headless)"),
    ):
        sp = sub.add_parser(name, help=hlp)
        sp.add_argument("--strategy", default="ema_cross", help="ema_cross | rsi_reversion | grid | dca")
        sp.add_argument("--params", help="JSON string or file with strategy params")
        sp.add_argument("--spec", help="StrategySpec JSON string or file (overrides --strategy)")
        sp.add_argument("--risk", help="JSON string or file with RiskConfig overrides")
        sp.add_argument("--symbol", default="BTCTMN")
        sp.add_argument("--resolution", default="1h")
        if name == "backtest":
            sp.add_argument("--initial", help="initial quote balance")
            sp.add_argument("--out", help="report directory")
        else:
            sp.add_argument("--speed", type=float, default=0.2, help="seconds per candle")
        sp.set_defaults(fn=fn)

    sp = sub.add_parser("kill", help="KILL SWITCH: stop all bots and cancel open orders")
    sp.add_argument("--api", default="http://127.0.0.1:8000")
    sp.set_defaults(fn=cmd_kill)
    sub.add_parser("reset-kill", help="clear the kill switch").set_defaults(fn=cmd_reset_kill)

    sp = sub.add_parser("serve", help="run the API")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8000)
    sp.add_argument("--reload", action="store_true")
    sp.set_defaults(fn=cmd_serve)

    sub.add_parser("data-stats", help="list available market data").set_defaults(fn=cmd_data_stats)
    sub.add_parser("record", help="(blocked) record live Wallex data").set_defaults(fn=cmd_blocked)
    sub.add_parser("backfill", help="(blocked) backfill Wallex history").set_defaults(fn=cmd_blocked)

    args = p.parse_args(argv)
    code: int = args.fn(args)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
