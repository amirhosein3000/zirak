"""`zirak agent ...` commands: train, backtest, shadow, live, report, verify, export, probe, flatten.

Runs are written under `<DATA_DIR>/runs/<name>/`, models under `<DATA_DIR>/models/<config name>/`.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from zirak.agent.config import AgentConfig
from zirak.agent.journal import Journal, dumps
from zirak.agent.model import MetaModel
from zirak.agent.report import build_report, report_markdown
from zirak.agent.verify import verify_run
from zirak.config import BACKEND_ROOT, Settings, load_settings
from zirak.models import Candle

DEFAULT_CONFIG = BACKEND_ROOT / "config" / "challenge.json"


def _cfg(args: argparse.Namespace) -> AgentConfig:
    path = Path(args.config) if getattr(args, "config", None) else DEFAULT_CONFIG
    return AgentConfig.load(path if path.exists() else None)


def _series(s: Settings, cfg: AgentConfig) -> tuple[dict[str, list[Candle]], dict[str, Any], str]:
    from zirak.data.source import build_replay

    replay, label = build_replay(s)
    wanted = [*cfg.all_markets, "USDTTMN"]
    series = {m: replay.series(m, cfg.resolution) for m in dict.fromkeys(wanted)}
    series = {m: c for m, c in series.items() if c}
    missing = [m for m in cfg.markets if m not in series]
    if missing:
        raise SystemExit(
            f"no {cfg.resolution} candles for {missing}: run `zirak backfill` first ({label} data)"
        )
    return series, replay.markets, label


def _model_dir(s: Settings, cfg: AgentConfig, arg: str | None) -> Path:
    return Path(arg) if arg else s.data_dir / "models" / cfg.name


def _load_model(s: Settings, cfg: AgentConfig, arg: str | None) -> MetaModel:
    path = _model_dir(s, cfg, arg)
    if (path / "model_card.json").exists():
        return MetaModel.load(path)
    print(f"no trained model at {path}: using the smoothed-prior fallback (run `zirak agent train`)")
    m = cfg.model
    return MetaModel(m.min_prob, m.min_ev_pct, m.kelly_ref, m.min_rows)


def cmd_train(args: argparse.Namespace) -> int:
    from zirak.agent.runner import costs_from, train_model

    s, cfg = load_settings(), _cfg(args)
    series, _, label = _series(s, cfg)
    model = train_model(cfg, series, costs_from(s))
    out = model.save(_model_dir(s, cfg, args.out))
    print(f"trained on {label} data -> {out}")
    print(json.dumps(model.card.to_dict(), indent=1, default=str))
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    from zirak.agent.runner import run_backtest

    s, cfg = load_settings(), _cfg(args)
    series, markets, label = _series(s, cfg)
    start = datetime.fromisoformat(args.start) if args.start else None
    end = datetime.fromisoformat(args.end) if args.end else None
    if args.days and not start:
        last = series[cfg.markets[0]][-1].ts
        start = last - timedelta(days=args.days)
    run_dir = s.data_dir / "runs" / (args.run or f"backtest-{datetime.now(UTC):%Y%m%d-%H%M%S}")
    model = _load_model(s, cfg, args.model) if args.model else None
    report = asyncio.run(
        run_backtest(cfg, series, markets, s, run_dir, start, end, walk_forward=model is None, model=model)
    )
    (run_dir / "report.md").write_text(report_markdown(report), encoding="utf-8")
    print(f"data: {label}  run: {run_dir}")
    print(report_markdown(report))
    return 0


def _live(args: argparse.Namespace, mode: str) -> int:
    from zirak.agent.runner import run_live
    from zirak.exchange.guard import live_blockers
    from zirak.exchange.wallex import WallexClient
    from zirak.llm.provider import build_llm

    s, cfg = load_settings(), _cfg(args)
    if mode == "live":
        blockers = live_blockers(s)
        if blockers:
            raise SystemExit("live trading blocked: " + "; ".join(blockers))
        if not args.i_understand_this_is_real_money:
            raise SystemExit(
                "refusing: add --i-understand-this-is-real-money after confirming the risk limits"
            )
    data = WallexClient(s)
    llm = build_llm(s)
    run_dir = s.data_dir / "runs" / (args.run or f"{cfg.name}-{mode}")
    model = _load_model(s, cfg, args.model)

    async def go() -> dict[str, Any]:
        try:
            return await run_live(
                cfg,
                s,
                run_dir,
                mode,
                data,
                model,
                None if llm.name == "mock" else llm,
                stop_after_s=args.duration,
            )
        finally:
            await data.close()

    print(f"{mode} run -> {run_dir}  (LLM: {llm.name}; stop with Ctrl+C or `zirak kill`)")
    try:
        report = asyncio.run(go())
        print(report_markdown(report))
    except KeyboardInterrupt:
        print("interrupted; state is saved, run the same command to resume")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    run = Path(args.run_dir)
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    cfg = AgentConfig.model_validate(manifest["config"])
    report = build_report(run, cfg, manifest["mode"])
    (run / "report.json").write_text(dumps(report), encoding="utf-8")
    (run / "report.md").write_text(report_markdown(report), encoding="utf-8")
    print(report_markdown(report))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    result = verify_run(Path(args.run_dir))
    print(json.dumps(result, indent=1, ensure_ascii=False, default=str))
    return 0 if result["ok"] else 1


def cmd_export(args: argparse.Namespace) -> int:
    """decisions.jsonl -> decisions.csv: one flat row per decision (the decision log for the judges)."""
    run = Path(args.run_dir)
    rows = Journal(run).read("decisions.jsonl")
    cols = [
        "id",
        "ts",
        "kind",
        "symbol",
        "setup",
        "action",
        "exit",
        "price",
        "tp_pct",
        "sl_pct",
        "model_prob",
        "model_ev_pct",
        "model_source",
        "model_id",
        "posture_stance",
        "posture_mult",
        "posture_source",
        "risk_value_tmn",
        "risk_bound_by",
        "qty",
        "pnl_tmn",
        "pnl_pct",
        "status",
        "reason_fa",
        "signal_fa",
    ]
    out = run / "decisions.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for d in rows:
            m, p, r = d.get("model") or {}, d.get("posture") or {}, d.get("risk") or {}
            flat = {
                **d,
                "model_prob": m.get("prob"),
                "model_ev_pct": m.get("ev_pct"),
                "model_source": m.get("source"),
                "model_id": m.get("id"),
                "posture_stance": p.get("stance"),
                "posture_mult": p.get("mult"),
                "posture_source": p.get("source"),
                "risk_value_tmn": r.get("value_tmn"),
                "risk_bound_by": r.get("bound_by"),
            }
            w.writerow(
                [
                    flat.get(c, "") if not isinstance(flat.get(c), dict) else json.dumps(flat.get(c))
                    for c in cols
                ]
            )
    print(f"wrote {out} ({len(rows)} decisions)")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    """Day-0 check on the real account (needs every live condition): read balances, plan limits and fees,
    place ONE tiny LIMIT buy far below the market, read it back, list open orders, cancel it, read again.
    Prints the raw shapes so the UNVERIFIED fields in docs/wallex-api can be confirmed."""
    import httpx

    from zirak.exchange.guard import live_blockers
    from zirak.exchange.wallex import WallexAPIError, WallexClient
    from zirak.models import OrderRequest, OrderType, Side

    s = load_settings()
    blockers = live_blockers(s)
    if blockers:
        raise SystemExit("probe needs live mode: " + "; ".join(blockers))
    if not args.yes:
        raise SystemExit(
            "this places one real (tiny, far-from-market) order and cancels it; add --yes to run"
        )
    c = WallexClient(s)

    async def go() -> None:
        try:
            print("balances:", {k: v for k, v in (await c.get_balances()).items() if v.total})

            async def optional(label: str, call: Callable[[], Awaitable[object]]) -> None:
                # Read-only extras: report a failure and keep going to the order check.
                try:
                    print(f"{label}:", await call())
                except (httpx.HTTPError, WallexAPIError) as e:
                    print(f"{label}: FAILED ({e})")

            if s.wallex_credit_account:
                await optional("active plan", c.get_active_package)
            if s.wallex_prop_package_id:
                pid = s.wallex_prop_package_id
                await optional("unavailable markets", lambda: c.get_unavailable_markets(pid))
            fees = await c.get_fees()
            print("fees:", {k: v for k, v in fees.items() if k == args.symbol})
            markets = {m.symbol: m for m in await c.get_markets()}
            m = markets[args.symbol]
            book = await c.get_order_book(args.symbol)
            assert book.best_bid is not None
            # 5 % below the bid: far enough not to fill, inside the band Wallex accepts around its fair
            # price (`fair_price.spot.max_acceptable_buy` = 8 % on 2026-10-23; 30 % away was rejected, 422)
            price = m.round_price(book.best_bid * Decimal("0.95"), Side.SELL)
            qty = m.round_qty(m.min_notional * Decimal("1.05") / price) + m.qty_step
            print(f"placing BUY {qty} {args.symbol} @ {price} (5 % below the best bid {book.best_bid})")
            try:
                o = await c.place_order(
                    OrderRequest(args.symbol, Side.BUY, OrderType.LIMIT, qty, price, "probe")
                )
            except WallexAPIError as e:
                print(f"order REJECTED: {e}")
                print(f"full body: {e.body}")
                raise SystemExit(1) from e
            print("placed:", o.to_dict())
            print("read back:", (await c.get_order(args.symbol, o.id)).to_dict())
            print("open orders:", [x.to_dict() for x in await c.get_open_orders(args.symbol)])
            print("canceled:", (await c.cancel_order(args.symbol, o.id)).to_dict())
            print("after cancel:", (await c.get_order(args.symbol, o.id)).to_dict())
        finally:
            await c.close()

    asyncio.run(go())
    return 0


def cmd_flatten(args: argparse.Namespace) -> int:
    """Sell every coin of the configured markets back to Toman (marketable limits, capped), then stop."""
    from zirak.agent.engine import Agent, Position
    from zirak.agent.runner import costs_from
    from zirak.exchange.guard import live_blockers
    from zirak.exchange.wallex import WallexClient
    from zirak.models import utcnow

    s, cfg = load_settings(), _cfg(args)
    if live_blockers(s, risk_reducing=False):
        raise SystemExit("flatten needs live mode (it sells on the real account)")
    if not args.yes:
        raise SystemExit("add --yes to sell every coin of the configured markets to Toman")
    c = WallexClient(s)

    async def go() -> None:
        try:
            markets = {m.symbol: m for m in await c.get_markets()}
            run_dir = s.data_dir / "runs" / f"{cfg.name}-flatten"
            agent = Agent(cfg, c, markets, MetaModel(), Journal(run_dir), costs_from(s), utcnow, s)
            bal = await c.get_balances()
            await c.cancel_all()
            for sym in cfg.markets:
                m, b = markets[sym], bal.get(markets[sym].base)
                if b is None or b.total < m.min_qty:
                    continue
                book = await c.get_order_book(sym)
                px = book.best_bid or Decimal(0)
                agent.last_price[sym] = px
                pos = Position(
                    sym,
                    "flatten",
                    "manual",
                    m.round_qty(b.total),
                    b.total * px,
                    px,
                    px,
                    px,
                    utcnow().isoformat(),
                    1,
                )
                await agent.exit_position(pos, "flatten", utcnow())
                print(f"{sym}: sell order for {pos.qty} sent")
        finally:
            await c.close()

    asyncio.run(go())
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    from zirak.agent.mcp_server import build_server

    build_server().run()
    return 0


def add_parser(sub: Any) -> None:
    ap = sub.add_parser("agent", help="the challenge trading agent (train / backtest / shadow / live / ...)")
    asub = ap.add_subparsers(dest="agent_cmd", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--config", help="agent config JSON (default backend/config/challenge.json)")

    p = asub.add_parser("train", help="train the ML meta-labeler on all available history")
    common(p)
    p.add_argument("--out", help="model directory (default DATA_DIR/models/<config name>)")
    p.set_defaults(fn=cmd_train)

    p = asub.add_parser("backtest", help="walk-forward backtest through the same engine")
    common(p)
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--days", type=float, help="backtest the last N days (earlier data trains the model)")
    p.add_argument("--model", help="use this fixed model instead of walk-forward retraining")
    p.add_argument("--run", help="run directory name")
    p.set_defaults(fn=cmd_backtest)

    for mode, hlp in (
        ("shadow", "live Wallex data, paper orders (shadow test)"),
        ("live", "REAL orders on the account"),
    ):
        p = asub.add_parser(mode, help=hlp)
        common(p)
        p.add_argument("--model", help="model directory (default DATA_DIR/models/<config name>)")
        p.add_argument("--run", help="run name; reuse it to resume after a restart (default <name>-<mode>)")
        p.add_argument("--duration", type=float, help="stop after N seconds")
        if mode == "live":
            p.add_argument("--i-understand-this-is-real-money", action="store_true")
        p.set_defaults(fn=lambda a, m=mode: _live(a, m))

    for name, fn, hlp in (
        ("report", cmd_report, "rebuild a run's report"),
        ("verify", cmd_verify, "recompute every AI decision of a run from its logs"),
        ("export", cmd_export, "decision log -> decisions.csv"),
    ):
        p = asub.add_parser(name, help=hlp)
        p.add_argument("run_dir")
        p.set_defaults(fn=fn)

    p = asub.add_parser("probe", help="day-0 check: one tiny far-from-market order, read back, cancel")
    p.add_argument("--symbol", default="USDTTMN")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(fn=cmd_probe)

    p = asub.add_parser("flatten", help="sell every coin of the configured markets to Toman (real account)")
    common(p)
    p.add_argument("--yes", action="store_true")
    p.set_defaults(fn=cmd_flatten)

    sub.add_parser(
        "mcp", help="Zirak MCP server (stdio): read-only analysis and run tools for AI agents"
    ).set_defaults(fn=cmd_mcp)
