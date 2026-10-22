"""End-to-end demo flow through the API, fully offline (sample data + mock LLM)."""

import time
from pathlib import Path

from fastapi.testclient import TestClient

from zirak.api.main import create_app
from zirak.config import SAMPLE_DATA_DIR, Settings


def client(tmp_path: Path) -> TestClient:
    s = Settings(
        data_dir=tmp_path,
        db_path=tmp_path / "none.sqlite",
        kill_file=tmp_path / "KILL",
        replay_dir=SAMPLE_DATA_DIR,
    )
    return TestClient(create_app(s))


def test_demo_flow(tmp_path: Path) -> None:
    with client(tmp_path) as c:
        health = c.get("/api/health").json()
        assert health["live_trading"] is False and health["llm"] == "mock"

        markets = c.get("/api/markets").json()
        assert {m["symbol"] for m in markets} >= {"BTCTMN", "USDTTMN"}

        brief = c.get("/api/markets/BTCTMN/brief").json()
        assert "توصیهٔ مالی نیست" in brief["brief_fa"]

        parsed = c.post(
            "/api/strategy/parse", json={"text": "وقتی بیت‌کوین ۵٪ ریخت، با ۱۰٪ سرمایه بخر و با ۳٪ سود بفروش"}
        ).json()
        spec = parsed["spec"]
        assert spec and parsed["description_fa"]

        report = c.post("/api/backtest", json={"strategy": "rules", "spec": spec}).json()
        assert "metrics" in report and report["equity_curve"]
        assert c.get(f"/api/backtests/{report['id']}").status_code == 200
        if report["trades"]:
            ex = c.post("/api/explain", json={"entry": report["trades"][0]}).json()
            assert ex["explanation_fa"]

        st = c.post("/api/bot/start", json={"strategy": "rules", "spec": spec, "speed_s": 0.05}).json()
        assert st["running"]
        time.sleep(0.5)
        st = c.get("/api/bot/status").json()
        assert st["bot"]["candles_seen"] > 0

        killed = c.post("/api/kill").json()
        assert killed["killed"] and killed["kill_engaged"] and not killed["running"]
        assert killed["bot"]["killed"] and killed["bot"]["open_orders"] == []
        # Cannot restart while the kill switch is engaged.
        assert c.post("/api/bot/start", json={"strategy": "ema_cross"}).status_code == 409
        assert c.post("/api/kill/reset").json()["kill_engaged"] is False


def test_visual_builder_endpoints(tmp_path: Path) -> None:
    with client(tmp_path) as c:
        vocab = c.get("/api/strategy/vocabulary").json()
        assert {"drop_from_high", "rsi_below"} <= {x["kind"] for x in vocab["conditions"]}
        assert any(t["key"] == "shock_reversal" for t in vocab["templates"])
        assert any(m["symbol"] == "BTCTMN" for m in vocab["markets"])

        bad = c.post("/api/strategy/describe", json={"spec": {"symbol": "BTCTMN", "entry": []}}).json()
        assert bad["spec"] is None and bad["error_fa"]
        spec = {"symbol": "BTCTMN", "entry": [{"kind": "drop_from_high", "pct": 3, "minutes": 1440}]}
        ok = c.post("/api/strategy/describe", json={"spec": spec}).json()
        assert ok["error_fa"] is None and ok["spec"]["entry"][0]["lookback"] == 24 and ok["description_fa"]

        scan = c.post(
            "/api/backtest/markets", json={"strategy": "rules", "spec": ok["spec"], "period": "30d"}
        ).json()
        assert {r["symbol"] for r in scan["rows"]} >= {"BTCTMN", "ETHTMN"}
        assert all(r["symbol"].endswith("TMN") for r in scan["rows"]) and scan["headline_fa"]
