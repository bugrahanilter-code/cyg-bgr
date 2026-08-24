import { useState } from "react";

import { BarSeries } from "@/charts/BarSeries";
import { LineAreaChart } from "@/charts/LineAreaChart";
import { Badge } from "@/components/Badge";
import { Panel } from "@/components/Panel";
import { ParamsForm } from "@/components/ParamsForm";
import { StatCard } from "@/components/StatCard";
import { Banner, ErrorState, Loading } from "@/components/StateViews";
import { Toggle } from "@/components/Toggle";
import { REFRESH_SLOW, useApiMutation, useOnceQuery, usePolledQuery } from "@/hooks/useApi";
import { backtestService, settingsService, strategyService } from "@/services/tradingService";
import type { BacktestRunPayload } from "@/services/tradingService";
import { useAppState } from "@/state/appStateContext";
import type { BacktestDetail } from "@/types/api";
import {
  daysAgoIso,
  formatCurrency,
  formatDateTime,
  formatPercent,
  formatPrice,
  formatSignedCurrency,
  pnlClass,
  titleCase,
  toIsoDate,
} from "@/utils/format";
import { sideTone } from "@/utils/tone";

const TIMEFRAMES = ["5m", "15m", "30m", "1h", "4h", "1d"];

interface FormState {
  strategy_key: string;
  symbol: string;
  timeframe: string;
  start: string;
  end: string;
  starting_capital: number;
  leverage: number;
  taker_fee_pct: number;
  slippage_pct: number;
  funding_rate_pct_per_8h: number;
  apply_funding: boolean;
  respect_daily_limits: boolean;
  walk_forward: boolean;
  walk_forward_folds: number;
}

const INITIAL_FORM: FormState = {
  strategy_key: "trend_following",
  symbol: "BTC/USDT",
  timeframe: "15m",
  start: daysAgoIso(120),
  end: toIsoDate(new Date()),
  starting_capital: 10000,
  leverage: 2,
  taker_fee_pct: 0.04,
  slippage_pct: 0.02,
  funding_rate_pct_per_8h: 0.01,
  apply_funding: true,
  respect_daily_limits: true,
  walk_forward: false,
  walk_forward_folds: 4,
};

function MetricGrid({ metrics }: { metrics: BacktestDetail["metrics"] }) {
  const value = (key: string): number => Number(metrics[key] ?? 0);
  const optional = (key: string): string => {
    const raw = metrics[key];
    return raw === null || raw === undefined ? "-" : Number(raw).toFixed(2);
  };

  return (
    <div className="grid grid-4">
      <StatCard
        label="Total return"
        value={formatPercent(value("total_return_pct"))}
        tone={pnlClass(value("total_return_pct")) as "positive" | "negative" | "neutral"}
        hint={"Final balance " + formatCurrency(value("final_balance"))}
      />
      <StatCard
        label="Net PnL"
        value={formatSignedCurrency(value("net_pnl"))}
        tone={pnlClass(value("net_pnl")) as "positive" | "negative" | "neutral"}
        hint={"Gross " + formatSignedCurrency(value("gross_pnl"))}
      />
      <StatCard
        label="Trades"
        value={value("total_trades")}
        hint={value("winning_trades") + "W / " + value("losing_trades") + "L"}
      />
      <StatCard label="Win rate" value={value("win_rate_pct").toFixed(1) + "%"} />
      <StatCard label="Profit factor" value={optional("profit_factor")} />
      <StatCard label="Expectancy" value={formatCurrency(value("expectancy"))} />
      <StatCard
        label="Max drawdown"
        value={formatPercent(-value("max_drawdown_pct"))}
        tone="warning"
      />
      <StatCard label="Sharpe" value={optional("sharpe_ratio")} />
      <StatCard label="Sortino" value={optional("sortino_ratio")} />
      <StatCard label="Calmar" value={optional("calmar_ratio")} />
      <StatCard
        label="Max consecutive losses"
        value={value("max_consecutive_losses")}
        hint={"Longest win streak " + value("max_consecutive_wins")}
      />
      <StatCard
        label="Average trade"
        value={(value("average_trade_duration_seconds") / 3600).toFixed(1) + "h"}
        hint={value("exposure_trades_per_day").toFixed(2) + " trades/day"}
      />
      <StatCard label="Fees" value={formatCurrency(value("total_fees"))} />
      <StatCard label="Funding" value={formatCurrency(value("total_funding"))} />
      <StatCard label="Slippage" value={formatCurrency(value("total_slippage"))} />
      <StatCard
        label="Average win / loss"
        value={formatCurrency(value("average_win"))}
        hint={"Average loss " + formatCurrency(value("average_loss"))}
      />
    </div>
  );
}

export function BacktestLabPage() {
  const { pushToast } = useAppState();
  const [form, setForm] = useState<FormState>(INITIAL_FORM);
  const [params, setParams] = useState<Record<string, unknown>>({});
  const [result, setResult] = useState<BacktestDetail | null>(null);

  const strategies = usePolledQuery(["strategies"], strategyService.list, REFRESH_SLOW);
  const settings = useOnceQuery(["settings"], settingsService.get);
  const history = usePolledQuery(["backtests"], () => backtestService.list(20), REFRESH_SLOW);

  const selected = (strategies.data ?? []).find((item) => item.key === form.strategy_key);
  const symbols = settings.data?.trading.enabled_symbols ?? ["BTC/USDT", "ETH/USDT"];

  const run = useApiMutation(
    (payload: BacktestRunPayload) => backtestService.run(payload),
    [["backtests"]],
    {
      onSuccess: (data) => {
        setResult(data);
        pushToast("Backtest finished", "success");
      },
      onError: (error) => pushToast(error.message, "error"),
    },
  );

  const load = useApiMutation((id: number) => backtestService.detail(id), [], {
    onSuccess: (data) => setResult(data),
  });

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function submit() {
    run.mutate({
      strategy_key: form.strategy_key,
      symbol: form.symbol,
      timeframe: form.timeframe,
      start: form.start + "T00:00:00",
      end: form.end + "T23:59:59",
      starting_capital: form.starting_capital,
      leverage: form.leverage,
      params,
      taker_fee_pct: form.taker_fee_pct,
      slippage_pct: form.slippage_pct,
      funding_rate_pct_per_8h: form.funding_rate_pct_per_8h,
      apply_funding: form.apply_funding,
      respect_daily_limits: form.respect_daily_limits,
      walk_forward: form.walk_forward,
      walk_forward_folds: form.walk_forward_folds,
    });
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Backtest Lab</h1>
          <p>
            Bar-by-bar simulation with realistic costs. Decisions are taken on closed candles
            and filled at the next open, so the results contain no look-ahead bias.
          </p>
        </div>
      </div>

      <Banner tone="warning">
        A backtest describes the past. It is not a prediction and it is not a profit
        guarantee. Optimising parameters until the curve looks good is called overfitting and
        it is the fastest way to lose real money.
      </Banner>

      <Panel title="Configuration">
        <div className="grid grid-4">
          <div className="field">
            <label htmlFor="strategy">Strategy</label>
            <select
              id="strategy"
              value={form.strategy_key}
              onChange={(event) => {
                update("strategy_key", event.target.value);
                setParams({});
              }}
            >
              {(strategies.data ?? []).map((item) => (
                <option key={item.key} value={item.key}>
                  {item.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="symbol">Market</label>
            <select
              id="symbol"
              value={form.symbol}
              onChange={(event) => update("symbol", event.target.value)}
            >
              {symbols.map((symbol) => (
                <option key={symbol} value={symbol}>
                  {symbol}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="timeframe">Timeframe</label>
            <select
              id="timeframe"
              value={form.timeframe}
              onChange={(event) => update("timeframe", event.target.value)}
            >
              {TIMEFRAMES.map((timeframe) => (
                <option key={timeframe} value={timeframe}>
                  {timeframe}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="capital">Starting capital</label>
            <input
              id="capital"
              type="number"
              min={100}
              value={form.starting_capital}
              onChange={(event) => update("starting_capital", Number(event.target.value))}
            />
          </div>
          <div className="field">
            <label htmlFor="start">Start date</label>
            <input
              id="start"
              type="date"
              value={form.start}
              onChange={(event) => update("start", event.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="end">End date</label>
            <input
              id="end"
              type="date"
              value={form.end}
              onChange={(event) => update("end", event.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="leverage">Leverage</label>
            <input
              id="leverage"
              type="number"
              min={1}
              max={20}
              value={form.leverage}
              onChange={(event) => update("leverage", Number(event.target.value))}
            />
          </div>
          <div className="field">
            <label htmlFor="fee">Taker fee %</label>
            <input
              id="fee"
              type="number"
              step={0.005}
              value={form.taker_fee_pct}
              onChange={(event) => update("taker_fee_pct", Number(event.target.value))}
            />
          </div>
          <div className="field">
            <label htmlFor="slippage">Slippage %</label>
            <input
              id="slippage"
              type="number"
              step={0.005}
              value={form.slippage_pct}
              onChange={(event) => update("slippage_pct", Number(event.target.value))}
            />
          </div>
          <div className="field">
            <label htmlFor="funding">Funding % per 8h</label>
            <input
              id="funding"
              type="number"
              step={0.001}
              value={form.funding_rate_pct_per_8h}
              onChange={(event) => update("funding_rate_pct_per_8h", Number(event.target.value))}
            />
          </div>
          <div className="field">
            <label>Apply funding</label>
            <Toggle
              checked={form.apply_funding}
              onChange={(value) => update("apply_funding", value)}
            />
          </div>
          <div className="field">
            <label>Respect daily limits</label>
            <Toggle
              checked={form.respect_daily_limits}
              onChange={(value) => update("respect_daily_limits", value)}
            />
          </div>
          <div className="field">
            <label>Walk-forward analysis</label>
            <Toggle
              checked={form.walk_forward}
              onChange={(value) => update("walk_forward", value)}
            />
            <small>Splits the period into in-sample and out-of-sample windows.</small>
          </div>
        </div>

        {selected && (
          <details>
            <summary className="small muted" style={{ cursor: "pointer", padding: "6px 0" }}>
              Strategy parameters (leave untouched to use the saved values)
            </summary>
            <div style={{ marginTop: 10 }}>
              <ParamsForm
                schema={selected.param_schema}
                values={{ ...selected.params, ...params }}
                onChange={(key, value) => setParams((current) => ({ ...current, [key]: value }))}
              />
            </div>
          </details>
        )}

        <div className="btn-row">
          <button
            type="button"
            className="btn btn-primary"
            disabled={run.isPending}
            onClick={submit}
          >
            {run.isPending ? "Running..." : "RUN BACKTEST"}
          </button>
          <button type="button" className="btn" onClick={() => setForm(INITIAL_FORM)}>
            Reset form
          </button>
        </div>
        {run.isPending && (
          <div className="small muted">
            Downloading candles and simulating. The first run for a period can take a while.
          </div>
        )}
        {run.error && <ErrorState error={run.error} />}
      </Panel>

      {result && (
        <>
          <Panel
            title="Result"
            subtitle={
              result.backtest.strategy_key +
              " | " +
              result.backtest.symbol +
              " | " +
              result.backtest.timeframe +
              " | " +
              result.backtest.candles_used +
              " candles"
            }
          >
            <MetricGrid metrics={result.metrics} />
          </Panel>

          <div className="grid grid-2">
            <Panel title="Equity curve">
              <LineAreaChart
                data={result.equity_curve.map((point) => ({
                  time: point.timestamp_ms,
                  value: point.equity,
                }))}
                height={280}
              />
            </Panel>
            <Panel title="Drawdown">
              <LineAreaChart
                data={result.drawdown_curve.map((point) => ({
                  time: point.time,
                  value: -point.drawdown_pct,
                }))}
                color="#ff5c6c"
                height={280}
                priceFormat="percent"
              />
            </Panel>
          </div>

          <div className="grid grid-2">
            <Panel title="Monthly performance">
              <BarSeries
                points={result.monthly_returns.map((month) => ({
                  label: month.month,
                  value: month.return_pct,
                }))}
                suffix="%"
              />
            </Panel>
            <Panel title="Trade distribution">
              <BarSeries
                points={(result.trade_distribution.histogram ?? []).map((bucket) => ({
                  label: bucket.from.toFixed(1),
                  value: bucket.count,
                }))}
                positiveColor="#4c8dff"
              />
              <div className="small muted">Return of each trade in percent, bucketed.</div>
            </Panel>
          </div>

          {result.walk_forward && (
            <Panel title="Walk-forward analysis" subtitle={result.walk_forward.warning}>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Fold</th>
                      <th className="numeric">In-sample return</th>
                      <th className="numeric">Out-of-sample return</th>
                      <th className="numeric">OOS trades</th>
                      <th className="numeric">OOS win rate</th>
                      <th>Best parameters</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.walk_forward.folds.map((fold) => (
                      <tr key={fold.fold}>
                        <td>{fold.fold}</td>
                        <td className="numeric">
                          {formatPercent(Number(fold.in_sample?.total_return_pct ?? 0))}
                        </td>
                        <td
                          className={
                            "numeric " + pnlClass(Number(fold.out_of_sample?.total_return_pct ?? 0))
                          }
                        >
                          {formatPercent(Number(fold.out_of_sample?.total_return_pct ?? 0))}
                        </td>
                        <td className="numeric">{fold.out_of_sample?.total_trades ?? 0}</td>
                        <td className="numeric">
                          {Number(fold.out_of_sample?.win_rate_pct ?? 0).toFixed(1)}%
                        </td>
                        <td className="small mono">
                          {Object.entries(fold.best_params)
                            .map(([key, value]) => titleCase(key) + "=" + String(value))
                            .join(", ") || "defaults"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          )}
        </>
      )}

      {result && result.trades.length > 0 && (
        <Panel title={"Trades (" + result.trades.length + ")"}>
          <div className="table-wrap" style={{ maxHeight: 420, overflowY: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>Opened</th>
                  <th>Closed</th>
                  <th>Side</th>
                  <th className="numeric">Entry</th>
                  <th className="numeric">Exit</th>
                  <th className="numeric">Net</th>
                  <th className="numeric">Return</th>
                  <th>Exit reason</th>
                </tr>
              </thead>
              <tbody>
                {result.trades.map((trade) => (
                  <tr key={trade.uid}>
                    <td>{formatDateTime(trade.opened_at)}</td>
                    <td>{formatDateTime(trade.closed_at)}</td>
                    <td>
                      <Badge tone={sideTone(trade.side)}>{trade.side}</Badge>
                    </td>
                    <td className="numeric">{formatPrice(trade.entry_price)}</td>
                    <td className="numeric">{formatPrice(trade.exit_price)}</td>
                    <td className={"numeric " + pnlClass(trade.net_pnl)}>
                      {formatSignedCurrency(trade.net_pnl)}
                    </td>
                    <td className={"numeric " + pnlClass(trade.return_pct)}>
                      {formatPercent(trade.return_pct)}
                    </td>
                    <td className="small">{trade.exit_reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      <Panel title="Previous runs">
        {history.isLoading ? (
          <Loading />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Created</th>
                  <th>Strategy</th>
                  <th>Market</th>
                  <th>Period</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {(history.data ?? []).length === 0 && (
                  <tr>
                    <td colSpan={6} className="table-empty">
                      No backtests have been run yet.
                    </td>
                  </tr>
                )}
                {(history.data ?? []).map((item) => (
                  <tr key={item.id}>
                    <td>{formatDateTime(item.created_at)}</td>
                    <td>{item.strategy_key}</td>
                    <td>
                      {item.symbol} {item.timeframe}
                    </td>
                    <td className="small">
                      {item.start_date.slice(0, 10)} to {item.end_date.slice(0, 10)}
                    </td>
                    <td>
                      <Badge tone={item.status === "COMPLETED" ? "success" : "danger"}>
                        {item.status}
                      </Badge>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-sm"
                        disabled={item.status !== "COMPLETED" || load.isPending}
                        onClick={() => load.mutate(item.id)}
                      >
                        Open
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </>
  );
}
