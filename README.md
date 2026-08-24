# Crypto Algorithmic Trading Platform

A modular, local-first cryptocurrency algorithmic trading platform for the ten
highest-volume Binance coins, with thirteen strategies, backtesting, paper
trading and (optional, off by default) live trading.

> ## THIS SYSTEM DOES NOT GUARANTEE ANY PROFIT
>
> Trading cryptocurrencies, especially with leverage, can lose you all of your
> money. Backtest and paper-trading results describe the past and are not a
> prediction of future returns. This software is an engineering and research
> project, not financial advice. You are responsible for every order it sends.

**Turkce kurulum rehberi:** [docs/KURULUM-TR.md](docs/KURULUM-TR.md)

---

## Table of contents

1. [What is this?](#1-what-is-this)
2. [How it works](#2-how-it-works)
3. [Architecture](#3-architecture)
4. [Installation](#4-installation)
5. [Docker](#5-docker)
6. [Binance API setup](#6-binance-api-setup)
7. [API permissions](#7-api-permissions)
8. [Where do I enter the API key?](#8-where-do-i-enter-the-api-key)
9. [How to run a backtest](#9-how-to-run-a-backtest)
10. [How to start paper trading](#10-how-to-start-paper-trading)
11. [How to enable live trading](#11-how-to-enable-live-trading)
12. [Risk settings](#12-risk-settings)
13. [The dashboard](#13-the-dashboard)
14. [Adding a new strategy](#14-adding-a-new-strategy)
15. [Changing the UI](#15-changing-the-ui)
16. [Running the tests](#16-running-the-tests)
17. [Team work on GitHub](#17-team-work-on-github)
18. [Troubleshooting](#18-troubleshooting)
19. [Security](#19-security)
20. [Emergency stop](#20-emergency-stop)

---

## 1. What is this?

A trading platform that runs entirely on your own computer. It has three modes:

| Mode | Market data | Orders | Money at risk |
| --- | --- | --- | --- |
| **Backtest** | Historical candles | None | None |
| **Paper** (default) | Real, live Binance data | Simulated with fees and slippage | None |
| **Live** | Real, live Binance data | **Real orders on Binance** | **Real money** |

It ships with thirteen independent, publicly documented strategies (4 safe,
5 medium risk, 4 risky - the level is shown in the dashboard), a strict Risk
Engine that can veto any of them, a reconciliation engine that compares local
state with the exchange, and a three-level emergency stop.

**Live trading is disabled by default and cannot start on its own.** Even with
API keys present the platform stays in paper mode until you explicitly enable
live trading in two separate places.

### Markets

The ten highest-volume Binance coins are created for you on first start:

```
BTC  ETH  SOL  XRP  BNB  DOGE  ZEC  HYPE  TRUMP  ENA   (all quoted in USDT)
```

Only **BTC/USDT and ETH/USDT are enabled for trading** by default. Adding a
market makes it available; switching it on is a separate tick in Settings,
because every enabled market multiplies the work the engine does and the number
of positions that can be opened.

The ranking is live: **Settings -> Add the 10 highest-volume coins** re-reads it
from Binance. Tokenised stocks and commodities (Binance lists SanDisk, gold,
SpaceX and others on the same venue) are filtered out on purpose — they follow
stock-market hours and gap over weekends, which every strategy here would
misread. Each coin appears once, so BTC/USDT and BTC/USDC never both get
enabled and quietly double your exposure to one asset.

## 2. How it works

Every 5 seconds the engine performs one cycle:

1. Refresh prices (WebSocket, with REST as a fallback).
2. Mark open positions to market, move trailing stops, check stop loss and take
   profit.
3. Reconcile the local database with the exchange periodically.
4. When a new candle closes, ask each enabled strategy for a decision.
5. Pass the decision to the Risk Engine, which approves or rejects it and, if
   approved, computes the position size.
6. Only then may the Execution Engine send an order.
7. Write everything to the trade journal and the event log.

If prices are stale, if the local state disagrees with Binance, if the daily
loss limit or profit target is reached, or if the emergency stop is armed, step
6 never happens.

## 3. Architecture

```
Market Data -> Market Regime -> Strategies -> Signals -> RISK ENGINE
   -> Portfolio -> Execution Engine -> Binance -> Trade Journal -> Dashboard
```

The dashboard is a read-only client of the backend REST API and contains no
trading logic. You can replace or delete it and the engine keeps working.

Full details: [docs/architecture.md](docs/architecture.md).

## 4. Installation

### Easiest path: Docker only

You need **Docker Desktop** and nothing else. No Python, no Node.js.

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and
   start it (wait until the whale icon says "running").
2. Open a terminal in this folder.
3. Copy the example environment file:

   ```bash
   cp .env.example .env
   ```

   On Windows PowerShell: `Copy-Item .env.example .env`

4. Open `.env` in a text editor and change `POSTGRES_PASSWORD` to anything you
   like. Leave the Binance fields empty for now.
5. Start everything:

   ```bash
   docker compose up --build
   ```

6. Open <http://localhost:3000> in your browser.

The first build takes several minutes. Later starts take seconds.

### If Docker cannot start

Docker Desktop needs CPU virtualization (Intel VT-x / AMD SVM) to be enabled in
the BIOS/UEFI. If it reports *"Virtualization support not detected"*, either
enable that setting in the BIOS, or skip Docker entirely and use the native
path below - the platform runs identically, with SQLite instead of PostgreSQL.

On Windows the quickest way is to double-click, in this order:

1. `scripts\start-backend.bat`  (leave the window open)
2. `scripts\start-frontend.bat` (leave the window open)

Then open <http://localhost:3000>.

### Manual path (for developers)

Requires Python 3.11+ and Node.js 20+. PostgreSQL is optional: without it, set
`DATABASE_URL=sqlite+pysqlite:///./data/dev.db` in `.env` and everything works.

```bash
# Backend
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# Frontend (second terminal)
cd frontend
npm install
npm run dev
```

Dashboard: <http://localhost:3000> - API docs: <http://localhost:8000/docs>

Without PostgreSQL you can set `DATABASE_URL=sqlite+pysqlite:///./data/dev.db`
in `.env` for a quick local run.

## 5. Docker

| Command | What it does |
| --- | --- |
| `docker compose up --build` | Build and start everything |
| `docker compose up -d` | Start in the background |
| `docker compose down` | Stop everything (data is kept) |
| `docker compose down -v` | Stop and **delete the database** |
| `docker compose logs -f backend` | Watch the backend logs |
| `docker compose restart backend` | Restart only the backend |

Three containers run: `db` (PostgreSQL), `backend` (FastAPI + trading engine),
`frontend` (nginx serving the dashboard and proxying `/api`).

## 6. Binance API setup

**You do not need an API key** for backtesting or paper trading. Market data is
public. Only add a key when you want to see your real balance or trade live.

1. Log in to Binance -> **API Management** -> **Create API**.
2. Give it a name, for example `local-trading-bot`.
3. Complete the security verification.
4. Copy the API key and the secret. **The secret is shown only once.**
5. Set the permissions as described in the next section.
6. Restrict the key to your own IP address.

For your first live test use the [Binance Futures testnet](https://testnet.binancefuture.com/)
and switch the "Use the Binance testnet" toggle on in the Settings page.

## 7. API permissions

| Permission | Setting |
| --- | --- |
| Enable Reading | **ON** |
| Enable Futures | ON only if you want futures trading |
| Enable Spot & Margin Trading | ON only if you want spot trading |
| **Enable Withdrawals** | **OFF - MUST STAY OFF** |
| IP restriction | Strongly recommended: your own IP only |

This platform never calls a withdrawal endpoint. If Binance reports that your
key has withdrawal permission enabled, the dashboard shows a red warning.

## 8. Where do I enter the API key?

Two options:

**A. In the dashboard (recommended).** Settings page -> Binance API. The secret
is encrypted before it is stored and is never displayed again, never sent back
to the browser and never written to the logs.

**B. In the `.env` file.** Set `BINANCE_API_KEY` and `BINANCE_API_SECRET`, then
restart the backend. `.env` is in `.gitignore` and must never be committed.

Press **Test connection** afterwards to confirm it works.

## 9. How to run a backtest

1. Open the **Backtest Lab** page.
2. Choose a strategy, a market (BTC/USDT or ETH/USDT), a timeframe and a date
   range. Start with 3 to 6 months on 15m.
3. Leave the cost settings at their defaults (0.04 percent taker fee, 0.02
   percent slippage, 0.01 percent funding per 8 hours) - they are realistic.
4. Press **RUN BACKTEST**. The first run downloads candles, so it can take a
   minute.
5. Read the results: total return, win rate, profit factor, maximum drawdown,
   Sharpe, Sortino, Calmar, fees, funding, equity curve, drawdown curve,
   monthly performance and every individual trade.

**Turn on Walk-forward analysis** for an honest evaluation: the period is split
into in-sample windows (used to pick parameters) and out-of-sample windows (used
only to measure). Only the out-of-sample numbers carry information.

Warning signs in a backtest: fewer than 30 trades, a profit factor above 3 with
few trades, results that collapse when a parameter changes slightly, or a
strategy that only works on one market.

## 10. How to start paper trading

Paper trading is the default. After `docker compose up` the platform is already
running in paper mode with a virtual balance (10,000 USDT by default).

1. Open the **Overview** page and check that Engine says *running* and Market
   Data is green.
2. Open **Strategies** and enable or disable strategies as you like.
3. Watch **Positions** and **Trades** fill up over the next hours or days.
4. Reset the virtual account any time from Settings -> Paper account.

Paper trading uses real live prices and applies the same fees, slippage and
funding as the backtester, so its results are comparable.

Run paper trading for **at least several weeks** before even thinking about
live trading.

## 11. How to enable live trading

Live trading requires all of the following. This is deliberate friction.

1. Store your Binance API key and secret (Settings page).
2. Press **Test connection** and see it succeed.
3. Confirm the withdrawal permission is disabled.
4. Review your risk settings.
5. Set `LIVE_TRADING_ENABLED=true` in `.env` and restart the backend:

   ```bash
   docker compose restart backend
   ```

6. Settings page -> Live trading -> tick both acknowledgements -> press
   **ENABLE LIVE TRADING**.

The top bar then shows a red `LIVE ORDERS ENABLED` badge. To go back to
simulation, press *Switch back to paper trading*.

**Start with the Binance testnet, then with a very small real balance.**

## 12. Risk settings

Everything on the **Risk Settings** page is editable and takes effect
immediately. Conservative defaults:

| Setting | Default | Meaning |
| --- | --- | --- |
| Risk per trade | 0.5% | Loss if the stop is hit |
| Daily profit target | 2.0% | Stop opening new trades once reached |
| Daily loss limit | 1.5% | Safe mode for the rest of the day |
| Max trades per day | 15 | Overtrading protection |
| Max concurrent positions | 2 | |
| Max consecutive losses | 3 | Pause after a losing streak |
| Cooldown | 30 min | Wait after a loss |
| Max drawdown | 15% | Hard stop for the whole account |
| Max leverage | 3 | Hard cap on every order |

Position size is **never** derived from leverage alone. It is computed from
equity, risk per trade and the distance to the stop loss, then capped by
exposure, available margin and the exchange rules (step size, tick size,
minimum notional).

When the daily target is reached the bot stops opening new trades and keeps
managing the open ones. It never increases risk to reach a target.

## 13. The dashboard

| Page | Contents |
| --- | --- |
| **Overview** | Status, balance, PnL (daily/weekly/monthly), drawdown, daily target progress, open positions, recent trades, equity curve |
| **Positions** | Size, entry, price, stop, target, leverage, margin, liquidation price, unrealised PnL, close buttons |
| **Trades** | Full journal with filters (date, market, strategy, direction, win/loss, paper/live/backtest) |
| **Strategies** | Enable/disable, current signal, confidence, regime, parameters, performance per strategy |
| **Comparison** | Every strategy side by side, overall and per market |
| **Backtest Lab** | Run backtests and walk-forward analysis, view charts and metrics |
| **Risk Settings** | Every risk limit |
| **System** | Health of each component, heartbeat, engine control, event log |
| **Settings** | Binance API, markets, timeframes, strategies, live trading, paper reset |

## 14. Adding a new strategy

```python
# backend/app/strategies/my_strategy.py
from pydantic import BaseModel, Field
from app.strategies.base import BaseStrategy

class MyParams(BaseModel):
    lookback: int = Field(default=20, ge=2, le=200)

class MyStrategy(BaseStrategy):
    key = "my_strategy"
    name = "My Strategy"
    family = "custom"
    description = "What it does and when it fails."
    params_model = MyParams

    @property
    def warmup_bars(self) -> int:
        return self.params.lookback + 10

    def prepare(self, frame, timeframe=""):
        ...   # vectorised, causal indicator columns

    def evaluate(self, prepared, index, *, symbol, timeframe, regime=None, position_side=None):
        ...   # read row `index` only, return a StrategySignal
```

Then register it in `backend/app/strategies/registry.py`, add tests, and write a
documentation page describing when it fails. The dashboard picks it up
automatically, including a settings form generated from the parameter schema.

See [docs/strategies/README.md](docs/strategies/README.md).

## 15. Changing the UI

The frontend is an ordinary Vite + React + TypeScript application in
`frontend/`. All backend calls live in `src/services/`, all types in
`src/types/api.ts`. There is no trading logic in the frontend, so you can
restyle it, rebuild it with another framework, or delete it entirely without
affecting the engine.

## 16. Running the tests

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

Tests use an in-memory database and a mock exchange; no internet and no API key
are needed. See [docs/testing.md](docs/testing.md).

```bash
cd frontend
npm run lint && npm run typecheck && npm run build
```

## 17. Team work on GitHub

Branch model:

```
main        production-ready, protected
  develop   integration branch
    feature/<name>   new features
    fix/<name>       bug fixes
    hotfix/<name>    urgent fixes branched from main
```

Workflow for a new contributor:

```bash
git clone <repository-url>
cd crypto-trading-platform
git checkout develop
git checkout -b feature/my-change
# ... make changes ...
cd backend && pytest && ruff check .
cd ../frontend && npm run lint && npm run typecheck
git commit -m "feat: add my change"
git push -u origin feature/my-change
# open a Pull Request into develop
```

Commit convention: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`.

CI (GitHub Actions) runs backend lint and tests, frontend lint, type check and
build, both Docker image builds, and a secret-hygiene check. To make a green CI
mandatory before merging: repository **Settings -> Branches -> Add rule** for
`main` and `develop`, tick *Require status checks to pass before merging* and
select the CI jobs.

Details: [CONTRIBUTING.md](CONTRIBUTING.md).

## 18. Troubleshooting

| Problem | Fix |
| --- | --- |
| Dashboard shows "The request timed out" | The backend is not running. `docker compose logs -f backend` |
| `docker: command not found` | Docker Desktop is not installed or not started |
| Port 3000 or 8000 already in use | Change `FRONTEND_PORT` / `BACKEND_PORT` in `.env` |
| Market Data is red | No internet, or Binance is unreachable from your country/network |
| "Binance authentication failed" | Wrong key/secret, or IP restriction blocks you |
| No trades appear | Normal. The strategies wait for their conditions; check Strategies for the current signal and reason |
| Backtest says "Not enough candles" | Choose a longer date range or a smaller timeframe |
| "Stored API credentials could not be decrypted" | `SECRET_KEY` changed - re-enter the keys |
| Database errors after an upgrade | `docker compose down -v` then `docker compose up --build` (deletes local data) |

## 19. Security

* API secrets are encrypted at rest and never sent to the frontend or the logs.
* The withdrawal permission is never used and must be disabled on your key.
* The API has no authentication and is meant for `localhost` only - do not
  expose port 8000 to the internet.
* `.env` is gitignored; CI fails if a `.env` file is ever committed.

Full details: [docs/security.md](docs/security.md).

## 20. Emergency stop

The red **EMERGENCY STOP** button in the top bar is always available and offers
three levels:

1. **Stop opening new trades** - existing positions keep their stop and target.
2. **Close every open position** - market orders for everything, then halt.
3. **Stop the whole system** - the engine stops and stays stopped, even after a
   restart, until you clear it.

The emergency stop is stored in the database, so a computer reboot cannot
silently resume trading.

---

## Licence

MIT - see [LICENSE](LICENSE). No warranty, no profit guarantee, not financial
advice.
