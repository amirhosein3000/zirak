"""Command line: `zirak <command>`. Run `zirak -h` for the list."""

from __future__ import annotations

import argparse
import asyncio
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from zirak.config import REPO_ROOT, SAMPLE_DATA_DIR, WALLEX_SAMPLE_DIR, load_settings


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
    from zirak.exchange.wallex import WallexClient

    s = load_settings()
    strat, risk, symbol, resolution = _strategy_from_args(args)
    replay, label = build_replay(s)
    live = WallexClient(s) if s.data_source == "wallex" else None
    if live is not None:
        label = "LIVE Wallex"
    runner = BotRunner(s, replay, live)

    async def run() -> None:
        await runner.start(strat, risk, symbol, resolution, speed_s=args.speed)
        print(
            f"paper bot started: {strat.key} on {symbol} {resolution} ({label} data, paper money). "
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


def cmd_research(args: argparse.Namespace) -> int:
    """Walk-forward research over every strategy x market x resolution; writes a JSON results file."""
    import json

    from zirak.backtest.walkforward import GRIDS, walk_forward
    from zirak.data.source import build_replay
    from zirak.fees import FeeModel

    s = load_settings()
    replay, label = build_replay(s)
    fees = FeeModel(s.fee_maker, s.fee_taker)
    # resolution -> (train, test) window in candles
    windows = {"1h": (480, 240), "4h": (120, 60), "1d": (120, 60)}
    symbols = _symbols(args, s.markets)
    results = []

    async def run() -> None:
        for res, (train, test) in windows.items():
            for symbol in symbols:
                series = replay.series(symbol, res)
                market = replay.markets.get(symbol)
                if market is None or len(series) < train + test + 100:
                    continue
                initial = s.paper_start_tmn if market.quote == "TMN" else s.paper_start_usdt
                for key in GRIDS:
                    wf = await walk_forward(
                        key, market, res, series, train, test, fees, s.slippage_bps, initial
                    )
                    results.append(wf.to_dict())
                    print(
                        f"{res:3s} {symbol:8s} {key:14s} oos {wf.oos_return_pct:+8.2f}% dd {wf.oos_max_dd_pct:7.2f}% "
                        f"trades {wf.oos_trades:3d} | b&h {wf.bh_return_pct:+8.2f}% dd {wf.bh_max_dd_pct:7.2f}% "
                        f"| {wf.verdict}"
                    )

    asyncio.run(run())
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "data": label,
        "fee_taker_pct": str(s.fee_taker_pct),
        "fee_maker_pct": str(s.fee_maker_pct),
        "slippage_bps": str(s.slippage_bps),
        "windows": windows,
    }
    out.write_text(
        json.dumps({"meta": meta, "results": results}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"wrote {out} ({sum(r['survives'] for r in results)} of {len(results)} configurations survive)")
    return 0


def cmd_compete(args: argparse.Namespace) -> int:
    """Competition mode (zirak/modules/competition.py): several paper strategies + team limits."""
    from zirak.data.source import build_replay
    from zirak.exchange.wallex import WallexClient
    from zirak.modules.competition import DEFAULT_CONFIG, Competition, CompetitionIn

    s = load_settings()
    cfg = CompetitionIn.model_validate(_json_arg(args.config) if args.config else DEFAULT_CONFIG)
    if args.speed is not None:
        cfg = cfg.model_copy(update={"speed_s": args.speed})
    replay, label = build_replay(s)
    live = WallexClient(s) if s.data_source == "wallex" else None
    comp = Competition(s, cfg, replay, live)

    async def run() -> None:
        await comp.start()
        print(
            f"competition '{cfg.name}' started: {len(cfg.entries)} entries on "
            f"{'LIVE Wallex' if live else label} data, paper money. Files: {comp.out_dir}"
        )
        print("Stop: Ctrl+C (orderly) or `zirak kill` (kill switch).")
        t0 = asyncio.get_running_loop().time()
        try:
            while comp.running:
                await asyncio.sleep(max(cfg.write_every_s, 1.0))
                perf = await comp.performance()
                print(
                    f"equity {perf['total_equity_tmn']} TMN  pnl {perf['pnl_pct']}%  "
                    f"dd {perf['drawdown_from_peak_pct']}%"
                )
                if args.duration and asyncio.get_running_loop().time() - t0 > args.duration:
                    break
        finally:
            await comp.stop()
            perf = await comp.performance()
            print("final:", {k: perf[k] for k in ("total_equity_tmn", "pnl_pct", "stopped_reason")})
            if live is not None:
                await live.close()

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


def _symbols(args: argparse.Namespace, default: list[str]) -> list[str]:
    return [x.strip().upper() for x in args.symbols.split(",")] if args.symbols else default


def cmd_backfill(args: argparse.Namespace) -> int:
    from zirak.data.recorder import backfill, save_markets
    from zirak.data.store import Store
    from zirak.exchange.wallex import WallexClient

    s = load_settings()
    symbols = _symbols(args, s.markets)
    days = {"1m": args.days_1m, "1h": args.days_1h, "1d": args.days_1d}

    async def run() -> None:
        client, store = WallexClient(s), Store(s.db_path)
        try:
            n = await save_markets(client, s.data_dir / "markets.json")
            print(f"saved {n} spot markets to {s.data_dir / 'markets.json'}")
            print(f"backfilling {', '.join(symbols)} into {s.db_path}")
            await backfill(client, store, symbols, days)
        finally:
            await client.close()
            store.close()

    asyncio.run(run())
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    import logging

    from zirak.data.recorder import Recorder, save_markets
    from zirak.data.store import Store
    from zirak.exchange.wallex import WallexClient

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    s = load_settings()
    symbols = _symbols(args, s.markets)
    status_path = s.data_dir / "recorder_status.json"

    async def run() -> None:
        client, store = WallexClient(s), Store(s.db_path)
        rec = Recorder(
            client,
            store,
            symbols,
            s.recorder_resolutions,
            s.recorder_candle_interval_s,
            s.recorder_book_interval_s,
            s.recorder_trades_interval_s,
            status_path,
        )
        try:
            await save_markets(client, s.data_dir / "markets.json")
            print(f"recording {', '.join(symbols)} ({', '.join(s.recorder_resolutions)}) into {s.db_path}")
            print(f"status file: {status_path}. Stop with Ctrl+C.")
            status = await rec.run(args.duration)
            print({k: v.__dict__ for k, v in status.tasks.items()})
        finally:
            await client.close()
            store.close()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("recorder stopped")
    return 0


def cmd_export_sample(args: argparse.Namespace) -> int:
    """Copy recent recorded candles (+ markets.json) from the DB into a CSV fixture directory."""
    from datetime import timedelta

    from zirak.data.store import Store, write_candles_csv
    from zirak.models import utcnow

    s = load_settings()
    out = Path(args.out)
    store = Store(s.db_path)
    since = {
        "1m": timedelta(days=args.days_1m),
        "1h": timedelta(days=args.days_1h),
        "1d": timedelta(days=args.days_1d),
    }
    try:
        for symbol in _symbols(args, s.markets):
            for res, delta in since.items():
                candles = store.load_candles(symbol, res, start=utcnow() - delta)
                if candles:
                    write_candles_csv(out / f"{symbol}_{res}.csv", candles)
                    print(f"  {symbol:8s} {res:3s} {len(candles):6d} candles")
    finally:
        store.close()
    if (s.data_dir / "markets.json").exists():
        snap = json.loads((s.data_dir / "markets.json").read_text(encoding="utf-8"))
        wanted = set(_symbols(args, s.markets))
        snap["markets"] = [m for m in snap["markets"] if m["symbol"] in wanted]
        (out / "markets.json").write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "README.md").write_text(
        "\n".join(
            [
                "# Real Wallex sample data",
                "",
                "Recorded from the public Wallex API with `zirak backfill` and exported with",
                f"`zirak export-sample` on {utcnow():%Y-%m-%d} (UTC). Candles: 1m, 1h, 1d;",
                "15m and 4h are derived on load. `markets.json` holds the real price/amount precision.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"sample written to {out}")
    return 0


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

    sp = sub.add_parser("research", help="walk-forward strategy research (out-of-sample only)")
    sp.add_argument("--symbols", help="comma list; default MARKETS")
    sp.add_argument("--out", default=str(REPO_ROOT / "docs" / "research-results.json"))
    sp.set_defaults(fn=cmd_research)

    sp = sub.add_parser("compete", help="competition mode: several paper strategies with team limits")
    sp.add_argument("--config", help="CompetitionIn JSON string or file (default: conservative preset)")
    sp.add_argument("--speed", type=float, help="replay: seconds per candle")
    sp.add_argument("--duration", type=float, help="stop after N seconds")
    sp.set_defaults(fn=cmd_compete)

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
    sp = sub.add_parser("backfill", help="download Wallex candle history into the DB")
    sp.add_argument("--symbols", help="comma list; default MARKETS")
    sp.add_argument("--days-1m", type=float, default=3)
    sp.add_argument("--days-1h", type=float, default=180)
    sp.add_argument("--days-1d", type=float, default=1000)
    sp.set_defaults(fn=cmd_backfill)

    sp = sub.add_parser("record", help="record live Wallex candles, order books and trades (runs for days)")
    sp.add_argument("--symbols", help="comma list; default MARKETS")
    sp.add_argument("--duration", type=float, help="stop after N seconds (default: run forever)")
    sp.set_defaults(fn=cmd_record)

    sp = sub.add_parser("export-sample", help="export recent recorded candles to a CSV fixture dir")
    sp.add_argument("--out", default=str(WALLEX_SAMPLE_DIR))
    sp.add_argument("--symbols", help="comma list; default MARKETS")
    sp.add_argument("--days-1m", type=float, default=1)
    sp.add_argument("--days-1h", type=float, default=60)
    sp.add_argument("--days-1d", type=float, default=400)
    sp.set_defaults(fn=cmd_export_sample)

    from zirak.agent.cli import add_parser as add_agent_parser

    add_agent_parser(sub)

    args = p.parse_args(argv)
    code: int = args.fn(args)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
