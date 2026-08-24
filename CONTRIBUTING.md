# Contributing

Thanks for helping to build this platform. Because this project can send real
orders with real money, contributions are held to a higher bar than usual:
**safety and testability come before features.**

## Development environment

```bash
git clone <repository-url>
cd crypto-trading-platform
cp .env.example .env          # never commit the result

# Backend
cd backend
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest                         # should pass before you change anything

# Frontend
cd ../frontend
npm install
npm run dev
```

For a full stack with PostgreSQL:

```bash
docker compose up --build
```

## Branch model

```
main               protected, always deployable
  develop          integration branch, PRs target this
    feature/<name> new functionality
    fix/<name>     bug fixes
    hotfix/<name>  urgent fix, branched from main, merged to main AND develop
```

Never push directly to `main`.

## Commit convention

```
feat:     a new user-visible capability
fix:      a bug fix
refactor: internal change, no behaviour change
test:     tests only
docs:     documentation only
chore:    tooling, dependencies, CI
perf:     performance work
```

Example: `feat(risk): add per-symbol exposure limit`

Write the body in the imperative mood and explain *why*, not *what*.

## Pull request rules

A PR is merged when:

1. CI is green (backend lint and tests, frontend lint, type check, build,
   Docker builds, secret check).
2. New behaviour has tests. Bug fixes have a regression test.
3. The trading safety checklist in the PR template is satisfied.
4. At least one other contributor has reviewed it.
5. It targets `develop` (or `main` for a hotfix).

Keep PRs small. A 200-line PR gets a real review; a 2000-line PR gets a rubber
stamp.

## Code standards

### Python

* Formatted and linted with **ruff** (`ruff format .`, `ruff check .`).
* Type hints on public functions; `mypy app` should not get worse.
* Line length 100.
* Docstrings explain *why*, especially for trading rules.
* No `print()` - use `app.core.logging.get_logger`.

### TypeScript

* `npm run lint` and `npm run typecheck` must pass.
* No trading logic in the frontend. Ever.
* All backend calls go through `src/services/`.
* No `any` unless justified with a comment.

## Non-negotiable trading rules

Any PR that breaks one of these will be rejected:

1. **Only the Execution Engine may send orders.** Strategies return signals.
2. **The Risk Engine keeps its veto.** Do not add a code path that bypasses it.
3. **No look-ahead bias.** Indicators stay causal; `evaluate()` may read only
   the row it is given; the backtester fills at the next bar's open.
4. **Live trading stays off by default** and keeps requiring two explicit
   confirmations.
5. **Secrets never** get hard-coded, logged, returned by an API, or committed.
6. **No withdrawal endpoint** may be added to the exchange layer.
7. **No profit claims.** Do not describe any strategy as guaranteed, reliable
   or risk-free, in code, docs or UI text.
8. **State mismatch blocks trading.** Do not weaken reconciliation.

## Adding a strategy

See [docs/strategies/README.md](docs/strategies/README.md). A new strategy must
ship with a documentation page that honestly describes when it loses money.

## Reporting a security issue

Do not open a public issue for anything involving key handling or order safety.
Contact the maintainers privately first.
