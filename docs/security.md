# Security model

## API key handling

| Rule | Where it is enforced |
| --- | --- |
| The secret is never hard-coded | `.env` / database only, `.env` is gitignored |
| The secret is encrypted at rest | `core/security.py` (Fernet, key derived from `SECRET_KEY`) |
| The secret never reaches the frontend | `credentials_service.masked_view()` returns a mask only |
| The secret never reaches the logs | `SecretRedactionFilter` in `core/logging.py` |
| Withdrawals are never called | No withdrawal endpoint exists in `exchange/` |
| The user is warned about withdrawal permission | Settings page + `check_permissions()` |

If you ever change `SECRET_KEY` you must re-enter the API keys: the old
ciphertext can no longer be decrypted (that is the point).

## How to create a safe Binance API key

1. Binance -> API Management -> Create API
2. Enable **Reading**
3. Enable **Futures** only if you intend to trade futures
4. Leave **Withdrawals DISABLED** - the platform never needs it
5. Restrict access to your own IP address
6. Test on the Binance **testnet** first

## Three switches before a real order

A real order can only be sent when all three are true:

1. `LIVE_TRADING_ENABLED=true` in `.env` (requires a backend restart)
2. Live trading confirmed in the dashboard, with both risk acknowledgements
3. `allow_real_orders=True` on the Execution Engine, which the application
   context sets only when 1 and 2 hold and credentials exist

If any of them is false the platform falls back to the simulated gateway.

## Other protections

* **Idempotent orders** - deterministic client order ids prevent a retry or a
  crash from opening a second position.
* **Order verification** - the exchange response is not trusted; the order
  state is read back before the position is recorded.
* **Reconciliation** - a mismatch between local state and Binance blocks all
  new entries and raises a CRITICAL event.
* **Persistent kill switch** - the emergency stop survives a restart.
* **Audit log** - every configuration change is recorded in `audit_logs`.

## Local deployment assumptions

The API has **no authentication**: it is designed to run on `localhost`. Do not
expose port 8000 to the internet. If you ever need remote access, put it behind
a VPN or an authenticating reverse proxy first.
