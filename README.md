# Crypto Algorithmic Trading Platform

A modular, local-first cryptocurrency algorithmic trading platform for the ten
highest-volume Binance coins, with fourteen strategies, backtesting, paper
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

It ships with fourteen independent, publicly documented strategies (4 safe,
6 medium risk, 4 risky - the level is shown in the dashboard), a strict Risk
Engine that can veto any of them, a reconciliation engine that compares local
state with the exchange, and a three-level emergency stop.

**Live trading is disabled by default and cannot start on its own.** Even with
API keys present the platform stays in paper mode until you explicitly enable
live trading in two separate places.

### Markets

**Every USDT perpetual on Binance is available** — 525 markets at the time of
writing. The **Markets** page lists all of them with live 24 hour statistics:
price, change, high, low, where the price sits inside the 24 hour range, quote
volume, the live bid/ask spread, ATR as a percentage of price, RSI, and
TradingView's technical rating. Search, sort and filter by volume; click any row
for the exchange rules, the cached candle history and a full TradingView chart.

Two states are deliberately kept apart:

* **Available** — the market exists in the database and can be backtested.
  *Markets -> Import every market* adds all of them in one action.
* **Enabled** — the trading engine actually evaluates it every candle.
  This is a separate click per market, because each enabled market adds one
  strategy evaluation per candle and one more position the risk engine has to
  supervise.

Only **BTC/USDT and ETH/USDT are enabled for trading** on a fresh install.

The most useful column is **round trip cost**: the taker fee in and out, the
slippage in and out, plus the live spread. That is what a strategy has to earn
on every single trade before it earns anything at all, and on most low-volume
markets it is larger than any edge found so far.

Tokenised stocks and commodity indices (Binance lists them on the same venue)
are filtered out by default — they follow stock-market hours and gap over
weekends, which every strategy here would misread.

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

### Automatic rotation into the top movers

The **Rotation** page ranks every tradable market by 24 hour change and makes the
top N the enabled trading set, on a schedule (hourly by default).

It ships **disabled and in dry run**, because it changes what the bot trades
without being asked. Turn it on in two steps: enable it, watch a dry run, then
clear the dry-run flag.

Read this before switching it on:

> Rotation is a **selection rule, not an edge**. A coin appears in the list
> *because* it already rose 24%; nothing here predicts that it continues. Every
> refresh also pays an exit on what leaves and an entry on what arrives, and
> transaction cost is the one factor that has beaten every strategy studied on
> this platform.

Quality filters keep the list tradable rather than merely dramatic:

| Filter | Default | Why |
| --- | ---: | --- |
| Minimum 24h volume | $50M | A coin that pumped on $2M cannot absorb an order |
| Maximum spread | 0.15% | Paid on every entry and every exit |
| Minimum listing age | 30 days | A coin listed last week has no history to backtest |
| Ignore moves above | 100% | Usually a listing event, not a trend |
| Cooldown after removal | 4 h | Stops a borderline coin thrashing in and out hourly |
| Maximum removals per run | 10 | One volatile hour cannot flush the whole book |

Three rules are not configurable:

* **A market with an open position is never disabled.** It keeps its slot until
  the position is flat, so the engine can still manage the exit. The run records
  these as *held open*.
* **Research-only markets can never be selected** (see the FX section below).
* **Every rejection carries a reason**, stored with the run, so "why is this coin
  not in the list" is answerable after the fact.

### Choosing a strategy from a sweep

*Matrix Backtest → select strategy* ranks every strategy/timeframe combination
in a sweep. It is deliberately hard to please, because picking the best of 84
combinations is the classic way to fool yourself: with that many draws the
winner's backtest number is roughly a 99th percentile result even if every
strategy is worthless.

A combination has to clear four independent bars:

1. **Enough trades** — 100 across markets, 20 on any market that counts.
2. **Breadth, not one lucky market** — profitable on at least 55% of the markets
   it was tested on, scored on the *median* market so one outlier cannot carry it.
3. **Cost-aware** — median expectancy positive in R, after fees, spread and slippage.
4. **Out of sample** — the winner is re-run on a window that was not used to
   choose it. Applying it is blocked until that is acknowledged.

`NO_QUALIFYING_COMBINATION` is a normal answer and is returned rather than the
least bad row, because handing back the least bad row is exactly how a losing
configuration ends up trading.

### Reference markets: gold and the FX majors

Four non-crypto markets are available alongside the coins. They exist as a
**control**, not as trading targets:

| Market | Source | Tradable | Round trip cost | Session |
| --- | --- | --- | ---: | --- |
| `XAU/USDT` | Binance perpetual | Yes | ~0.12% | 24/7 |
| `PAXG/USDT` | Binance (gold-backed token) | Yes | ~0.12% | 24/7 |
| `EUR/USD` | Yahoo Finance | **No** | ~0.02% | Mon 22:00 – Fri 22:00 UTC |
| `USD/JPY` | Yahoo Finance | **No** | ~0.02% | Mon 22:00 – Fri 22:00 UTC |

Every study on this platform has ended at the same wall: a small edge, eaten by
transaction costs. FX changes exactly one variable — a EUR/USD round trip costs
about six times less than a crypto perpetual. If a strategy is profitable there
and negative on crypto, the problem is cost. If it loses on both, the strategy
has no edge anywhere.

**EUR/USD and USD/JPY cannot be traded.** Binance has no FX market, so no order
could ever be filled. This is enforced in two places: the Risk Engine rejects
any signal on them with `SYMBOL_NOT_TRADABLE`, and the order validator refuses
them as a last check before anything leaves the process. The Markets page shows
them as *backtest only* with no Enable button.

Three traps worth knowing before reading any FX result:

1. **No volume.** Spot FX has no central exchange and therefore no consolidated
   volume — every bar reports zero. `vwap_pullback` is gated on volume and can
   never fire there: its zero trades mean *could not run*, not *found nothing*.
   Five more strategies (`adaptive_momentum`, `breakout_donchian`,
   `keltner_trend`, `mean_reversion`, `volatility_breakout`) read volume as one
   score component among several — they still trade, with that component
   permanently zero. The market detail panel names both groups. This split was
   measured, not assumed: every strategy was run twice over identical prices,
   once with volume and once with it zeroed.
2. **Weekend gaps.** The market closes on Friday and reopens on Sunday. Every
   strategy here assumes a continuous stream and reads the gap as an ordinary
   bar.
3. **Short intraday history.** Yahoo caps intraday data: 60 days below one hour,
   730 days at one hour, years at daily. A 15m FX sweep therefore covers two
   months whatever date range is requested.

Gold has none of these problems: `XAU/USDT` is a real Binance perpetual that
trades 24/7 with real volume and real Binance costs. It was listed in December
2025, so there is under a year of history.

### Testing everything at once (Matrix Backtest)

The **Matrix Backtest** page runs every selected strategy against every selected
market on every selected timeframe and stores one metric row per combination.

Press **Estimate the cost** before starting anything large. The work is not
proportional to the number of combinations, it is proportional to the number of
*candles* in them, and low timeframes dominate everything else:

| Grid | Backtests | CPU time | Candle storage |
| --- | ---: | ---: | ---: |
| 14 strategies x 30 markets x 6 timeframes x 12 months | 2,520 | ~53 min | 1.4 GB |
| 14 strategies x 50 markets x 6 timeframes x 12 months | 4,200 | ~1.5 h | 2.3 GB |
| 14 strategies x 523 markets x 6 timeframes x 12 months | 43,932 | ~15 h | 24 GB |
| **14 strategies x 523 markets x all 14 timeframes x 24 months** | **102,508** | **~397 h (16 days)** | **628 GB** |

The last row is what "every strategy on every coin on every timeframe" literally
means. It is not forbidden — the page will run it — but it is sixteen days of
uninterrupted CPU and 628 GB of candles, and roughly three quarters of that cost
comes from the 1m and 3m rows alone. Those are also precisely where transaction
costs have beaten the edge in every study run on this platform so far.

Results come back in three parts:

1. **What the grid says** — how many cells were profitable, how many beat simply
   holding the coin, and the average expectancy in R.
2. **Where does the edge survive?** — a strategy x timeframe heatmap. Green means
   the average cell earned more than it paid in costs; red means it did not.
3. **Every result** — the full table, filterable and sortable, with each cell's
   return next to the buy-and-hold return of the same coin over the same window.

Only cells with at least 20 trades are counted in the summary. A handful of
trades can show any number at all and mean nothing.

Sweeps store metrics only, not equity curves or trade lists — thousands of runs
would add gigabytes nobody reads. Every cell is reproducible: re-run an
interesting one in the Backtest Lab with the same settings to see it in full.

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

### Stop loss and take profit

Both are set in **Risk Settings**, and both are decided by one shared function
that the backtester and the live engine call. That matters: a rule changed here
moves the simulation and the real orders together, so a backtest keeps meaning
something.

**Stop loss** has three modes. The default, *strategy*, leaves each strategy's
own (usually ATR-based) stop alone. *Fixed* overrides every strategy with one
percentage. *Bounded* keeps the strategy's choice but clamps it. The
minimum/maximum band applies in every mode except *fixed* as a safety envelope —
a strategy asking for a 40% stop is a bug, not a choice.

Position size is calculated from the **decided** stop, so widening a stop
produces a *smaller* position, never more money at risk.

**Take profit** has four modes: *strategy*, *fixed percentage*, *risk multiple*
(2R means a target twice as far as the stop, and it follows a stop that was
widened or tightened), and *none*.

> **Measured on this platform:** removing the take profit improved expectancy in
> **70 of 93** paired tests — the same strategy, market and timeframe with only
> that one setting changed, across 6 strategies, 8 markets and 2 timeframes over
> 12 months. Median expectancy went from **+0.048R to +0.132R per trade**.
>
> The mechanism is the one trend traders describe: these systems earn from a few
> large winners that pay for many small losses, and a fixed target cuts exactly
> those winners short. The win rate *falls* when you remove it, which is why it
> looks wrong on a dashboard and is right on the equity curve.
>
> This is one year and one cost model, so treat it as a strong hypothesis rather
> than a settled fact — but it is a structural change verified across 93
> independent cells, which is far better evidence than picking the best of 74
> strategy/timeframe combinations.

**Trailing stop and break-even** are also here. A stop only ever moves toward
profit; loosening one is not possible. Both are off by default, and both cost
something: in the same test, trailing at 2% from 1R and moving to break-even at
1R each made results *worse* on BTC/USDT, because they convert winners into
scratches. They are tools, not free improvements.

**Minimum reward/risk** rejects an entry whose target is too close to its stop.
Off by default.

## 13. The dashboard

| Page | Contents |
| --- | --- |
| **Genel Bakış** (Overview) | Balance, PnL, drawdown, daily target, equity curve, open positions, recent trades, account reset |
| **Piyasalar** (Markets) | All 525 Binance markets with 24 hour statistics, search and sort, TradingView charts, enable/disable |
| **İşlemler** (Activity) | Open positions and the full trade journal, as two tabs of one page |
| **Stratejiler** (Strategies) | Enable/disable and tune each strategy, plus the side-by-side comparison |
| **Test** | One backtest in depth, or the whole strategy x market x timeframe grid, as two tabs |
| **Otomasyon** (Rotation) | Automatically enable the top 24 hour movers on a schedule, with quality filters and an audit trail |
| **Risk** | Position sizing, leverage band, stop loss, take profit, trailing, daily limits, market quality filters |
| **Sistem** (System) | Health of each component, heartbeat, engine control, event log |
| **Ayarlar** (Settings) | Binance API, markets, timeframes, live trading switch, paper account reset |

The interface is in Turkish. Nine destinations are grouped into three sections
(**İzle** / **Strateji** / **Yönet**) rather than listed flat, and pages that
show one subject at two scales share a route with a tab strip.

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

### Where the data comes from

Candles for strategies and backtests come from **Binance** and only from Binance:
the series a backtest runs on has to be the series the execution engine will be
filled against. **TradingView** supplies screener context (technical rating, RSI,
ATR, relative volume) shown on the Markets page, and the chart widget. No
TradingView value is ever read by a strategy, a risk check or an order.

The backend also serves a TradingView-compatible UDF datafeed at `/api/udf`, so
their Advanced Charts library can render our own candles when it is added.
Full reasoning: [docs/tradingview-integration.md](docs/tradingview-integration.md).

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
