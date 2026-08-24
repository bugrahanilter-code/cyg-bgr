"""Automatic rotation into the top 24 hour movers."""

from __future__ import annotations

from app.services import rotation_service
from app.services.rotation_service import RotationConfig, rank_candidates


def market(symbol: str, change: float, **overrides) -> dict:
    row = {
        "symbol": symbol,
        "change_24h_pct": change,
        "quote_volume_24h": 500_000_000.0,
        "spread_pct": 0.02,
        "last_price": 10.0,
        "tradable": True,
        "kind": "crypto",
        "onboard_date": None,
    }
    row.update(overrides)
    return row


class TestRanking:
    def test_sorted_by_24h_change_descending(self) -> None:
        rows = [market("A/USDT", 5.0), market("B/USDT", 25.0), market("C/USDT", 15.0)]
        accepted, _ = rank_candidates(rows, RotationConfig())
        assert [item["symbol"] for item in accepted] == ["B/USDT", "C/USDT", "A/USDT"]
        assert accepted[0]["rank"] == 1

    def test_thin_markets_are_rejected(self) -> None:
        """A coin that pumped on two million dollars cannot absorb an order."""
        rows = [market("PUMP/USDT", 40.0, quote_volume_24h=2_000_000.0)]
        accepted, rejected = rank_candidates(rows, RotationConfig())
        assert accepted == []
        assert "24h volume" in rejected[0]["reason"]

    def test_wide_spreads_are_rejected(self) -> None:
        rows = [market("WIDE/USDT", 40.0, spread_pct=1.2)]
        accepted, rejected = rank_candidates(rows, RotationConfig())
        assert accepted == []
        assert "spread" in rejected[0]["reason"]

    def test_absurd_moves_are_rejected_as_listing_events(self) -> None:
        rows = [market("NEW/USDT", 900.0)]
        accepted, rejected = rank_candidates(rows, RotationConfig())
        assert accepted == []
        assert "listing event" in rejected[0]["reason"]

    def test_fallers_are_rejected_by_the_default_floor(self) -> None:
        """In a red market a "top gainer" list otherwise fills with the coins
        that fell least, which is not what the rule is for."""
        rows = [market("DOWN/USDT", -8.0)]
        accepted, rejected = rank_candidates(rows, RotationConfig())
        assert accepted == []
        assert "24h change" in rejected[0]["reason"]

    def test_research_only_markets_can_never_be_selected(self) -> None:
        rows = [market("EUR/USD", 30.0, tradable=False, kind="forex")]
        accepted, rejected = rank_candidates(rows, RotationConfig())
        assert accepted == []
        assert rejected[0]["reason"] == "research-only market"

    def test_commodities_are_not_top_gainer_candidates(self) -> None:
        rows = [market("XAU/USDT", 3.0, kind="commodity")]
        accepted, rejected = rank_candidates(rows, RotationConfig())
        assert accepted == []
        assert "not a crypto market" in rejected[0]["reason"]

    def test_a_freshly_listed_coin_is_rejected(self) -> None:
        from app.core.time_utils import utcnow

        recent = int((utcnow().timestamp() - 3 * 86_400) * 1000)
        rows = [market("FRESH/USDT", 50.0, onboard_date=recent)]
        accepted, rejected = rank_candidates(rows, RotationConfig())
        assert accepted == []
        assert "listed" in rejected[0]["reason"]

    def test_every_rejection_carries_a_reason(self) -> None:
        rows = [market("THIN/USDT", 10.0, quote_volume_24h=1.0)]
        _, rejected = rank_candidates(rows, RotationConfig())
        assert rejected and rejected[0]["reason"]


class TestPlanning:
    """The plan decides the next enabled set without changing anything."""

    def _prepare(self, db, enabled: list[str]) -> None:
        from app.services import settings_service

        config = settings_service.get_trading_config(db)
        config.enabled_symbols = enabled
        settings_service.save_trading_config(db, config)

    def test_top_n_becomes_the_new_set(self, db) -> None:
        self._prepare(db, ["OLD/USDT"])
        rows = [market(f"C{i}/USDT", 50.0 - i) for i in range(30)]
        plan = rotation_service.plan_rotation(db, rows, RotationConfig(top_n=3))
        assert plan["added"] == ["C0/USDT", "C1/USDT", "C2/USDT"]
        assert plan["removed"] == ["OLD/USDT"]

    def test_markets_already_enabled_are_left_alone(self, db) -> None:
        self._prepare(db, ["C0/USDT", "C1/USDT"])
        rows = [market(f"C{i}/USDT", 50.0 - i) for i in range(5)]
        plan = rotation_service.plan_rotation(db, rows, RotationConfig(top_n=2))
        assert plan["added"] == []
        assert plan["removed"] == []
        assert set(plan["unchanged"]) == {"C0/USDT", "C1/USDT"}

    def test_removals_are_capped_per_run(self, db) -> None:
        """One volatile hour must not be able to flush the whole book.

        The cap is on removals because a removal closes a live position. That
        is the expensive half; additions are already bounded by top_n.
        """
        self._prepare(db, [f"OLD{i}/USDT" for i in range(10)])
        rows = [market(f"NEW{i}/USDT", 50.0 - i) for i in range(20)]
        plan = rotation_service.plan_rotation(
            db, rows, RotationConfig(top_n=20, max_changes_per_run=4)
        )
        assert len(plan["removed"]) <= 4

    def test_growing_to_the_target_is_not_throttled(self, db) -> None:
        """Going from ten enabled markets to a target of twenty is not churn,
        and throttling it would leave the set undersized for hours."""
        self._prepare(db, [f"C{i}/USDT" for i in range(10)])
        rows = [market(f"C{i}/USDT", 50.0 - i) for i in range(20)]
        plan = rotation_service.plan_rotation(
            db, rows, RotationConfig(top_n=20, max_changes_per_run=4)
        )
        assert len(plan["final_symbols"]) == 20
        assert plan["removed"] == []

    def test_the_final_set_is_the_current_set_plus_added_minus_removed(self, db) -> None:
        self._prepare(db, ["KEEP/USDT", "DROP/USDT"])
        rows = [market("KEEP/USDT", 30.0), market("NEW/USDT", 20.0)]
        plan = rotation_service.plan_rotation(db, rows, RotationConfig(top_n=2))
        assert "DROP/USDT" not in plan["final_symbols"]
        assert "KEEP/USDT" in plan["final_symbols"]
        assert "NEW/USDT" in plan["final_symbols"]


class TestOpenPositionsAreProtected:
    def test_a_market_with_an_open_position_is_never_disabled(self, db, monkeypatch) -> None:
        """Disabling a market mid-position would stop the engine managing the
        exit while real money is still at risk."""
        from app.services import settings_service

        config = settings_service.get_trading_config(db)
        config.enabled_symbols = ["HOLD/USDT", "DROP/USDT"]
        settings_service.save_trading_config(db, config)

        monkeypatch.setattr(
            rotation_service, "_symbols_with_open_positions", lambda _db: {"HOLD/USDT"}
        )
        rows = [market("NEW/USDT", 40.0)]
        plan = rotation_service.plan_rotation(db, rows, RotationConfig(top_n=1))

        assert "HOLD/USDT" not in plan["removed"]
        assert "HOLD/USDT" in plan["held_open"]
        assert "HOLD/USDT" in plan["final_symbols"]
        assert "DROP/USDT" in plan["removed"]


class TestConfigDefaults:
    def test_rotation_ships_disabled(self) -> None:
        """It changes what the bot trades, so it cannot be on by default."""
        assert RotationConfig().enabled is False

    def test_it_starts_in_dry_run(self) -> None:
        assert RotationConfig().dry_run is True

    def test_defaults_match_the_request(self) -> None:
        config = RotationConfig()
        assert config.top_n == 20
        assert config.interval_minutes == 60
