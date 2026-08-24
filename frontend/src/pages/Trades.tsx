import { useMemo, useState } from "react";

import { Badge } from "@/components/Badge";
import { Panel } from "@/components/Panel";
import { StatCard } from "@/components/StatCard";
import { ErrorState, Loading } from "@/components/StateViews";
import { REFRESH_SLOW, usePolledQuery } from "@/hooks/useApi";
import { strategyService, tradeService } from "@/services/tradingService";
import type { TradeFilters } from "@/services/tradingService";
import {
  formatCurrency,
  formatDateTime,
  formatDuration,
  formatPercent,
  formatPrice,
  formatQuantity,
  formatSignedCurrency,
  pnlClass,
} from "@/utils/format";
import { sideTone } from "@/utils/tone";

const MODES = ["", "paper", "live", "backtest"];
const SIDES = ["", "LONG", "SHORT"];
const RESULTS = ["", "win", "loss"];

export function TradesPage() {
  const [filters, setFilters] = useState<TradeFilters>({ mode: "paper", limit: 200 });

  const strategies = usePolledQuery(["strategies"], strategyService.list, REFRESH_SLOW);
  const { data, isLoading, error } = usePolledQuery(
    ["trades", filters],
    () => tradeService.list(filters),
    REFRESH_SLOW,
  );

  const trades = useMemo(() => data ?? [], [data]);

  const totals = useMemo(() => {
    const net = trades.reduce((sum, trade) => sum + trade.net_pnl, 0);
    const wins = trades.filter((trade) => trade.is_win).length;
    const fees = trades.reduce((sum, trade) => sum + trade.fees, 0);
    const funding = trades.reduce((sum, trade) => sum + trade.funding, 0);
    return {
      net,
      wins,
      losses: trades.length - wins,
      winRate: trades.length > 0 ? (wins / trades.length) * 100 : 0,
      fees,
      funding,
    };
  }, [trades]);

  function update(patch: Partial<TradeFilters>) {
    setFilters((current) => ({ ...current, ...patch }));
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Trades</h1>
          <p>
            One row per completed round trip. Backtest, paper and live trades share the same
            journal so the numbers are directly comparable.
          </p>
        </div>
      </div>

      <Panel title="Filters">
        <div className="grid grid-4">
          <div className="field">
            <label htmlFor="mode">Mode</label>
            <select
              id="mode"
              value={filters.mode ?? ""}
              onChange={(event) => update({ mode: event.target.value || undefined })}
            >
              {MODES.map((mode) => (
                <option key={mode} value={mode}>
                  {mode === "" ? "All" : mode}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="symbol">Symbol</label>
            <input
              id="symbol"
              type="text"
              placeholder="BTC/USDT"
              value={filters.symbol ?? ""}
              onChange={(event) => update({ symbol: event.target.value || undefined })}
            />
          </div>
          <div className="field">
            <label htmlFor="strategy">Strategy</label>
            <select
              id="strategy"
              value={filters.strategy ?? ""}
              onChange={(event) => update({ strategy: event.target.value || undefined })}
            >
              <option value="">All</option>
              {(strategies.data ?? []).map((strategy) => (
                <option key={strategy.key} value={strategy.key}>
                  {strategy.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="side">Direction</label>
            <select
              id="side"
              value={filters.side ?? ""}
              onChange={(event) => update({ side: event.target.value || undefined })}
            >
              {SIDES.map((side) => (
                <option key={side} value={side}>
                  {side === "" ? "All" : side}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="result">Result</label>
            <select
              id="result"
              value={filters.result ?? ""}
              onChange={(event) => update({ result: event.target.value || undefined })}
            >
              {RESULTS.map((result) => (
                <option key={result} value={result}>
                  {result === "" ? "All" : result}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="limit">Rows</label>
            <input
              id="limit"
              type="number"
              min={10}
              max={2000}
              value={filters.limit ?? 200}
              onChange={(event) => update({ limit: Number(event.target.value) })}
            />
          </div>
        </div>
      </Panel>

      <div className="grid grid-4">
        <StatCard
          label="Net PnL"
          value={formatSignedCurrency(totals.net)}
          tone={pnlClass(totals.net) as "positive" | "negative" | "neutral"}
        />
        <StatCard label="Trades" value={trades.length} hint={totals.wins + "W / " + totals.losses + "L"} />
        <StatCard label="Win rate" value={totals.winRate.toFixed(1) + "%"} />
        <StatCard
          label="Costs"
          value={formatCurrency(totals.fees + totals.funding)}
          hint={"Fees " + formatCurrency(totals.fees) + " | Funding " + formatCurrency(totals.funding)}
        />
      </div>

      <Panel title="Trade journal">
        {isLoading && !data ? (
          <Loading />
        ) : error ? (
          <ErrorState error={error} />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Closed</th>
                  <th>Mode</th>
                  <th>Symbol</th>
                  <th>Side</th>
                  <th>Strategy</th>
                  <th className="numeric">Size</th>
                  <th className="numeric">Entry</th>
                  <th className="numeric">Exit</th>
                  <th className="numeric">Gross</th>
                  <th className="numeric">Fees</th>
                  <th className="numeric">Funding</th>
                  <th className="numeric">Net</th>
                  <th className="numeric">Return</th>
                  <th>Duration</th>
                  <th>Regime</th>
                  <th>Exit reason</th>
                </tr>
              </thead>
              <tbody>
                {trades.length === 0 && (
                  <tr>
                    <td colSpan={16} className="table-empty">
                      No trades match these filters.
                    </td>
                  </tr>
                )}
                {trades.map((trade) => (
                  <tr key={trade.uid} title={trade.entry_reason}>
                    <td>{formatDateTime(trade.closed_at)}</td>
                    <td>
                      <Badge tone={trade.mode === "live" ? "danger" : "neutral"}>
                        {trade.mode}
                      </Badge>
                    </td>
                    <td>{trade.symbol}</td>
                    <td>
                      <Badge tone={sideTone(trade.side)}>{trade.side}</Badge>
                    </td>
                    <td>{trade.strategy_key}</td>
                    <td className="numeric">{formatQuantity(trade.quantity)}</td>
                    <td className="numeric">{formatPrice(trade.entry_price)}</td>
                    <td className="numeric">{formatPrice(trade.exit_price)}</td>
                    <td className={"numeric " + pnlClass(trade.gross_pnl)}>
                      {formatSignedCurrency(trade.gross_pnl)}
                    </td>
                    <td className="numeric muted">{formatCurrency(trade.fees)}</td>
                    <td className="numeric muted">{formatCurrency(trade.funding)}</td>
                    <td className={"numeric " + pnlClass(trade.net_pnl)}>
                      {formatSignedCurrency(trade.net_pnl)}
                    </td>
                    <td className={"numeric " + pnlClass(trade.return_pct)}>
                      {formatPercent(trade.return_pct)}
                    </td>
                    <td>{formatDuration(trade.duration_seconds)}</td>
                    <td className="small muted">{trade.market_regime}</td>
                    <td className="small">{trade.exit_reason}</td>
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
