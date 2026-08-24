"""Load a strategy configuration file into the platform database.

    .venv/Scripts/python.exe scripts/apply_config.py ../config/adaptive_momentum.yaml

The dashboard remains the source of truth at runtime; this script exists so a
researched configuration can be reproduced exactly, reviewed in a pull request
and applied to a fresh install in one command.

Nothing here can enable live trading. That still requires the environment flag
and the explicit dashboard confirmation.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
import json
from typing import Any

from app.core.logging import get_logger
from app.database.init_db import init_database
from app.database.session import SessionLocal
from app.risk.config import RiskConfig
from app.services import settings_service
from app.strategies.registry import create_strategy

logger = get_logger(__name__)


def _load(path: Path) -> dict[str, Any]:
    """Read a YAML or JSON configuration file.

    PyYAML is optional: a JSON file works just as well and keeps the backend
    dependency list short.
    """
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise SystemExit(
                "PyYAML is not installed. Either 'pip install pyyaml' or use a .json file."
            ) from exc
        return yaml.safe_load(text)
    return json.loads(text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply a strategy config file")
    parser.add_argument("path", help="Path to a .yaml or .json configuration file")
    parser.add_argument("--dry-run", action="store_true", help="Validate without saving")
    args = parser.parse_args()

    document = _load(Path(args.path))
    strategy_block = document.get("strategy") or {}
    name = strategy_block.get("name")
    if not name:
        raise SystemExit("The file must contain strategy.name")

    # Flatten the readable nested layout into the flat parameter model.
    params: dict[str, Any] = {}
    for section in ("indicators", "filters", "exits"):
        params.update(strategy_block.get(section) or {})
    params.update(strategy_block.get("params") or {})

    strategy = create_strategy(name, params)
    validated = strategy.params_dict()
    print(f"Strategy '{name}' parameters validated:")
    for key, value in sorted(validated.items()):
        print(f"  {key:26s} {value}")

    risk_block = document.get("risk") or {}
    risk = RiskConfig(**risk_block) if risk_block else None
    if risk is not None:
        print("\nRisk configuration validated:")
        for key, value in sorted(risk.model_dump().items()):
            print(f"  {key:26s} {value}")

    if args.dry_run:
        print("\nDry run: nothing was written.")
        return

    init_database()
    with SessionLocal() as db:
        settings_service.set_json_setting(
            db, f"strategy_params:{name}", validated, "Applied from a config file"
        )
        if risk is not None:
            settings_service.save_risk_config(db, risk)

        trading_block = document.get("trading") or {}
        if trading_block:
            config = settings_service.get_trading_config(db)
            for key, value in trading_block.items():
                if hasattr(config, key) and key not in ("mode",):
                    setattr(config, key, value)
            settings_service.save_trading_config(db, config)
            print("\nTrading configuration updated (mode was left untouched).")

    print("\nConfiguration applied. Live trading was NOT enabled by this script.")


if __name__ == "__main__":
    main()
