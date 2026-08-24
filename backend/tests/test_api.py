"""API smoke tests. They also verify the live-trading safety defaults."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_root_contains_the_disclaimer(client: TestClient) -> None:
    payload = client.get("/").json()
    assert "guarantee" in payload["disclaimer"].lower()


def test_openapi_is_available(client: TestClient) -> None:
    assert client.get("/openapi.json").status_code == 200


def test_system_status(client: TestClient) -> None:
    payload = client.get("/api/system/status").json()
    assert payload["mode"] in ("paper", "backtest", "live")
    assert payload["emergency_stop_level"] == "NONE"


def test_live_trading_is_off_by_default(client: TestClient) -> None:
    payload = client.get("/api/system/status").json()
    assert payload["live_trading_confirmed"] is False


def test_health_report_lists_components(client: TestClient) -> None:
    payload = client.get("/api/system/health").json()
    names = {component["name"] for component in payload["components"]}
    assert {"Market Data", "Risk Engine", "Execution Engine", "Reconciliation"} <= names


def test_strategies_endpoint(client: TestClient) -> None:
    payload = client.get("/api/strategies").json()
    assert len(payload) == 14
    keys = {item["key"] for item in payload}
    assert {"trend_following", "breakout_donchian", "mean_reversion"} <= keys
    assert {"golden_cross", "supertrend_follow", "rsi_divergence"} <= keys
    for item in payload:
        assert item["param_schema"]["properties"]
        assert item["risk_level"] in ("safe", "medium", "risky")


def test_strategies_are_returned_safest_first(client: TestClient) -> None:
    payload = client.get("/api/strategies").json()
    order = {"safe": 0, "medium": 1, "risky": 2}
    levels = [order[item["risk_level"]] for item in payload]
    assert levels == sorted(levels)


def test_strategy_can_be_disabled_and_enabled(client: TestClient) -> None:
    assert client.put("/api/strategies/mean_reversion", json={"enabled": False}).status_code == 200
    payload = client.get("/api/strategies/mean_reversion").json()
    assert payload["enabled"] is False
    client.put("/api/strategies/mean_reversion", json={"enabled": True})


def test_strategy_parameters_are_validated(client: TestClient) -> None:
    response = client.put("/api/strategies/trend_following", json={"params": {"fast_ema": -5}})
    assert response.status_code >= 400


def test_risk_settings_round_trip(client: TestClient) -> None:
    current = client.get("/api/risk").json()["config"]
    current["risk_per_trade_pct"] = 0.75
    response = client.put("/api/risk", json=current)
    assert response.status_code == 200
    assert client.get("/api/risk").json()["config"]["risk_per_trade_pct"] == 0.75


def test_risk_settings_reject_impossible_values(client: TestClient) -> None:
    current = client.get("/api/risk").json()["config"]
    current["risk_per_trade_pct"] = 500
    assert client.put("/api/risk", json=current).status_code == 422


def test_dashboard_overview(client: TestClient) -> None:
    payload = client.get("/api/dashboard/overview").json()
    assert "account" in payload and "risk" in payload and "positions" in payload
    assert payload["account"]["balance"] >= 0
    assert payload["risk"]["daily_profit_target_pct"] > 0


def test_settings_never_expose_the_api_secret(client: TestClient) -> None:
    payload = client.get("/api/settings").json()
    serialised = str(payload).lower()
    assert "api_secret" not in serialised or "***" in serialised
    assert "secret" not in payload.get("exchange", {})


def test_credentials_require_the_withdrawal_confirmation(client: TestClient) -> None:
    response = client.post(
        "/api/exchange/credentials",
        json={
            "api_key": "test-api-key-value",
            "api_secret": "test-api-secret-value",
            "market_type": "futures",
            "testnet": True,
            "withdrawal_disabled_confirmed": False,
        },
    )
    assert response.status_code == 400


def test_live_trading_requires_the_environment_flag(client: TestClient) -> None:
    response = client.post(
        "/api/trading/live/confirm",
        json={
            "confirmed": True,
            "acknowledge_risk": True,
            "acknowledge_no_profit_guarantee": True,
        },
    )
    assert response.status_code == 403


def test_emergency_stop_flow(client: TestClient) -> None:
    response = client.post(
        "/api/system/emergency-stop", json={"level": "HALT_NEW_ENTRIES", "reason": "test"}
    )
    assert response.status_code == 200
    assert client.get("/api/system/status").json()["emergency_stop_level"] == "HALT_NEW_ENTRIES"

    client.post("/api/system/emergency-stop", json={"level": "NONE", "reason": "cleared"})
    assert client.get("/api/system/status").json()["emergency_stop_level"] == "NONE"


def test_trades_endpoint_accepts_filters(client: TestClient) -> None:
    response = client.get("/api/trades", params={"mode": "paper", "limit": 5})
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_live_checklist(client: TestClient) -> None:
    payload = client.get("/api/trading/live/checklist").json()
    assert payload["env_flag_enabled"] is False
    assert payload["ready"] is False
    assert len(payload["items"]) == 5
