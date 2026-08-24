import { useEffect, useState } from "react";

import { Badge } from "@/components/Badge";
import { Panel } from "@/components/Panel";
import { Banner, ErrorState, Loading } from "@/components/StateViews";
import { Toggle } from "@/components/Toggle";
import { REFRESH_SLOW, useApiMutation, usePolledQuery } from "@/hooks/useApi";
import {
  exchangeService,
  settingsService,
  strategyService,
  tradingService,
} from "@/services/tradingService";
import { useAppState } from "@/state/appStateContext";
import { formatDateTime } from "@/utils/format";

const TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"];
const HIGHER_TIMEFRAMES = ["1h", "4h", "12h", "1d"];

function ApiCredentialsPanel() {
  const { pushToast } = useAppState();
  const status = usePolledQuery(["exchange-status"], exchangeService.status, REFRESH_SLOW);
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [marketType, setMarketType] = useState("futures");
  const [testnet, setTestnet] = useState(true);
  const [confirmed, setConfirmed] = useState(false);

  const save = useApiMutation(
    () =>
      exchangeService.saveCredentials({
        api_key: apiKey,
        api_secret: apiSecret,
        market_type: marketType,
        testnet,
        withdrawal_disabled_confirmed: confirmed,
      }),
    [["exchange-status"], ["settings"], ["system-status"]],
    {
      onSuccess: (response) => {
        pushToast(response.message, "success");
        setApiKey("");
        setApiSecret("");
      },
      onError: (error) => pushToast(error.message, "error"),
    },
  );

  const test = useApiMutation(() => exchangeService.test(), [["exchange-status"]], {
    onSuccess: (result) => pushToast(String(result.message ?? "Connection tested"), "info"),
    onError: (error) => pushToast(error.message, "error"),
  });

  const remove = useApiMutation(
    () => exchangeService.deleteCredentials(),
    [["exchange-status"], ["settings"]],
    { onSuccess: (response) => pushToast(response.message, "success") },
  );

  const view = status.data;

  return (
    <Panel
      title="Binance API"
      subtitle="Market data works without a key. A key is only needed for balances and live trading."
      actions={
        <Badge tone={view?.configured ? "success" : "neutral"}>
          {view?.configured ? "CONNECTED" : "NOT CONFIGURED"}
        </Badge>
      }
    >
      <Banner tone="warning">
        When you create the API key on Binance: enable reading (and futures if you need it),
        and keep <strong>withdrawals DISABLED</strong>. Restrict the key to your own IP
        address. This platform never calls a withdrawal endpoint and never shows your secret
        again once it is saved.
      </Banner>

      {view?.withdrawal_permission_warning && (
        <Banner tone="danger">
          Binance reports that this API key has the withdrawal permission enabled. Disable it
          immediately.
        </Banner>
      )}

      <div className="grid grid-2">
        <div className="field">
          <label htmlFor="api-key">API key</label>
          <input
            id="api-key"
            type="text"
            autoComplete="off"
            placeholder={view?.api_key_masked || "Paste your API key"}
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="api-secret">API secret</label>
          <input
            id="api-secret"
            type="password"
            autoComplete="off"
            placeholder="Never displayed again after saving"
            value={apiSecret}
            onChange={(event) => setApiSecret(event.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="market-type">Market</label>
          <select
            id="market-type"
            value={marketType}
            onChange={(event) => setMarketType(event.target.value)}
          >
            <option value="futures">USD-M Futures</option>
            <option value="spot">Spot</option>
          </select>
        </div>
        <div className="field">
          <label>Use the Binance testnet</label>
          <Toggle checked={testnet} onChange={setTestnet} label={testnet ? "Testnet" : "Real exchange"} />
          <small>Start with the testnet. It behaves like the real exchange without real money.</small>
        </div>
      </div>

      <label className="checkbox-row">
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(event) => setConfirmed(event.target.checked)}
        />
        I confirm that the withdrawal permission is disabled on this API key.
      </label>

      <div className="btn-row">
        <button
          type="button"
          className="btn btn-primary"
          disabled={!apiKey || !apiSecret || !confirmed || save.isPending}
          onClick={() => save.mutate(undefined)}
        >
          Save credentials
        </button>
        <button
          type="button"
          className="btn"
          disabled={test.isPending}
          onClick={() => test.mutate(undefined)}
        >
          Test connection
        </button>
        <button
          type="button"
          className="btn btn-danger"
          disabled={!view?.configured || remove.isPending}
          onClick={() => remove.mutate(undefined)}
        >
          Delete stored credentials
        </button>
      </div>

      {view && (
        <div className="grid grid-3 small">
          <div className="definition">
            <span>Stored key</span>
            <span>{view.api_key_masked || "-"}</span>
          </div>
          <div className="definition">
            <span>Source</span>
            <span>{view.source}</span>
          </div>
          <div className="definition">
            <span>Last test</span>
            <span>{view.last_tested_at ? formatDateTime(view.last_tested_at) : "never"}</span>
          </div>
        </div>
      )}
      {view?.last_test_message && <div className="small muted">{view.last_test_message}</div>}
    </Panel>
  );
}

function LiveTradingPanel() {
  const { pushToast } = useAppState();
  const checklist = usePolledQuery(
    ["live-checklist"],
    tradingService.liveChecklist,
    REFRESH_SLOW,
  );
  const [acknowledgeRisk, setAcknowledgeRisk] = useState(false);
  const [acknowledgeNoGuarantee, setAcknowledgeNoGuarantee] = useState(false);

  const confirm = useApiMutation(
    (enable: boolean) =>
      tradingService.confirmLive({
        confirmed: enable,
        acknowledge_risk: acknowledgeRisk,
        acknowledge_no_profit_guarantee: acknowledgeNoGuarantee,
      }),
    [["live-checklist"], ["system-status"], ["settings"], ["overview"]],
    {
      onSuccess: (response) => pushToast(response.message, "success"),
      onError: (error) => pushToast(error.message, "error"),
    },
  );

  const data = checklist.data;

  return (
    <Panel
      title="Live trading"
      subtitle="Disabled by default. Two separate confirmations are required."
      actions={
        <Badge tone={data?.confirmed ? "danger" : "neutral"}>
          {data?.confirmed ? "LIVE ORDERS ENABLED" : "SIMULATION ONLY"}
        </Badge>
      }
    >
      <Banner tone="danger">
        Live trading uses real money and can lose all of it. This software gives no profit
        guarantee. Test with paper trading and the Binance testnet first, and start with an
        amount you can afford to lose entirely.
      </Banner>

      <ul className="list-reset">
        {(data?.items ?? []).map((item) => (
          <li key={item.key} className="definition">
            <span>{item.label}</span>
            <span>{item.done ? "OK" : "MISSING"}</span>
          </li>
        ))}
        <li className="definition">
          <span>LIVE_TRADING_ENABLED in the .env file</span>
          <span>{data?.env_flag_enabled ? "true" : "false"}</span>
        </li>
      </ul>

      {!data?.env_flag_enabled && (
        <Banner tone="info">
          To even make live trading possible, set LIVE_TRADING_ENABLED=true in your .env file
          and restart the backend. This is a deliberate extra step.
        </Banner>
      )}

      <label className="checkbox-row">
        <input
          type="checkbox"
          checked={acknowledgeRisk}
          onChange={(event) => setAcknowledgeRisk(event.target.checked)}
        />
        I understand that I can lose my entire balance.
      </label>
      <label className="checkbox-row">
        <input
          type="checkbox"
          checked={acknowledgeNoGuarantee}
          onChange={(event) => setAcknowledgeNoGuarantee(event.target.checked)}
        />
        I understand that no strategy in this platform guarantees a profit.
      </label>

      <div className="btn-row">
        <button
          type="button"
          className="btn btn-danger"
          disabled={
            !data?.env_flag_enabled ||
            !acknowledgeRisk ||
            !acknowledgeNoGuarantee ||
            confirm.isPending ||
            data?.confirmed
          }
          onClick={() => confirm.mutate(true)}
        >
          ENABLE LIVE TRADING
        </button>
        <button
          type="button"
          className="btn"
          disabled={!data?.confirmed || confirm.isPending}
          onClick={() => confirm.mutate(false)}
        >
          Switch back to paper trading
        </button>
      </div>
    </Panel>
  );
}

export function SettingsPage() {
  const { pushToast } = useAppState();
  const settings = usePolledQuery(["settings"], settingsService.get, REFRESH_SLOW);
  const strategies = usePolledQuery(["strategies"], strategyService.list, REFRESH_SLOW);
  const [symbols, setSymbols] = useState<string[]>([]);
  const [timeframe, setTimeframe] = useState("15m");
  const [higherTimeframe, setHigherTimeframe] = useState("4h");
  const [leverage, setLeverage] = useState(2);
  const [autoStart, setAutoStart] = useState(true);
  const [resetBalance, setResetBalance] = useState(10000);
  const [clearHistory, setClearHistory] = useState(false);

  useEffect(() => {
    const trading = settings.data?.trading;
    if (trading && symbols.length === 0) {
      setSymbols(trading.enabled_symbols);
      setTimeframe(trading.timeframe);
      setHigherTimeframe(trading.higher_timeframe);
      setLeverage(trading.leverage);
      setAutoStart(trading.auto_start_engine);
    }
  }, [settings.data, symbols.length]);

  const saveTrading = useApiMutation(
    () =>
      settingsService.updateTrading({
        enabled_symbols: symbols,
        timeframe,
        higher_timeframe: higherTimeframe,
        leverage,
        auto_start_engine: autoStart,
      }),
    [["settings"], ["system-status"], ["overview"]],
    {
      onSuccess: (response) => pushToast(response.message, "success"),
      onError: (error) => pushToast(error.message, "error"),
    },
  );

  const resetPaper = useApiMutation(
    () => tradingService.resetPaper(resetBalance, clearHistory),
    [["overview"], ["trades"], ["positions"]],
    {
      onSuccess: (response) => pushToast(response.message, "success"),
      onError: (error) => pushToast(error.message, "error"),
    },
  );

  const toggleStrategy = useApiMutation(
    (payload: { key: string; enabled: boolean }) =>
      strategyService.update(payload.key, { enabled: payload.enabled }),
    [["strategies"], ["settings"]],
    { onSuccess: () => pushToast("Strategy updated", "success") },
  );

  if (settings.isLoading && !settings.data) {
    return <Loading />;
  }
  if (settings.error) {
    return <ErrorState error={settings.error} />;
  }

  const available = settings.data?.environment.supported_symbols ?? ["BTC/USDT", "ETH/USDT"];

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Settings</h1>
          <p>API access, markets, timeframes and the live trading switch.</p>
        </div>
      </div>

      <ApiCredentialsPanel />

      <Panel title="Markets and timeframes">
        <div className="grid grid-3">
          <div className="field">
            <label>Markets</label>
            {available.map((symbol) => (
              <label className="checkbox-row" key={symbol}>
                <input
                  type="checkbox"
                  checked={symbols.includes(symbol)}
                  onChange={(event) =>
                    setSymbols((current) =>
                      event.target.checked
                        ? [...current, symbol]
                        : current.filter((item) => item !== symbol),
                    )
                  }
                />
                {symbol}
              </label>
            ))}
          </div>
          <div className="field">
            <label htmlFor="tf">Strategy timeframe</label>
            <select id="tf" value={timeframe} onChange={(event) => setTimeframe(event.target.value)}>
              {TIMEFRAMES.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
            <small>The candle the strategies evaluate.</small>
          </div>
          <div className="field">
            <label htmlFor="htf">Higher timeframe</label>
            <select
              id="htf"
              value={higherTimeframe}
              onChange={(event) => setHigherTimeframe(event.target.value)}
            >
              {HIGHER_TIMEFRAMES.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
            <small>Used to confirm the trend direction.</small>
          </div>
          <div className="field">
            <label htmlFor="lev">Leverage</label>
            <input
              id="lev"
              type="number"
              min={1}
              max={20}
              value={leverage}
              onChange={(event) => setLeverage(Number(event.target.value))}
            />
            <small>The Risk Engine still caps this with its own maximum.</small>
          </div>
          <div className="field">
            <label>Start the engine automatically</label>
            <Toggle checked={autoStart} onChange={setAutoStart} />
          </div>
        </div>
        <div className="btn-row">
          <button
            type="button"
            className="btn btn-primary"
            disabled={saveTrading.isPending || symbols.length === 0}
            onClick={() => saveTrading.mutate(undefined)}
          >
            Save
          </button>
        </div>
      </Panel>

      <Panel title="Strategies">
        {(strategies.data ?? []).map((strategy) => (
          <div className="row-between" key={strategy.key}>
            <div>
              <strong>{strategy.name}</strong>
              <div className="small muted">{strategy.description}</div>
            </div>
            <Toggle
              checked={strategy.enabled}
              onChange={(value) => toggleStrategy.mutate({ key: strategy.key, enabled: value })}
            />
          </div>
        ))}
      </Panel>

      <LiveTradingPanel />

      <Panel title="Paper account">
        <div className="grid grid-3">
          <div className="field">
            <label htmlFor="reset-balance">Starting balance</label>
            <input
              id="reset-balance"
              type="number"
              min={100}
              value={resetBalance}
              onChange={(event) => setResetBalance(Number(event.target.value))}
            />
          </div>
          <div className="field">
            <label>Also delete the paper history</label>
            <Toggle checked={clearHistory} onChange={setClearHistory} />
          </div>
        </div>
        <div className="btn-row">
          <button
            type="button"
            className="btn btn-warning"
            disabled={resetPaper.isPending}
            onClick={() => resetPaper.mutate(undefined)}
          >
            Reset the paper account
          </button>
        </div>
        <small className="muted">
          Close every open paper position first. Live balances are never touched by this
          button.
        </small>
      </Panel>
    </>
  );
}
