import { useState } from "react";

import { Panel } from "@/components/Panel";
import { ErrorState, Loading } from "@/components/StateViews";
import { REFRESH_SLOW, usePolledQuery } from "@/hooks/useApi";
import { strategyService } from "@/services/tradingService";
import type { PerformanceSummary } from "@/types/api";
import { formatCurrency, formatPercent, formatSignedCurrency, pnlClass } from "@/utils/format";

const MODES = ["paper", "live", "backtest"];

function MetricRow({ label, summary }: { label: string; summary: PerformanceSummary }) {
  return (
    <tr>
      <td>{label}</td>
      <td className="numeric">{summary.trades}</td>
      <td className={"numeric " + pnlClass(summary.net_pnl)}>
        {formatSignedCurrency(summary.net_pnl)}
      </td>
      <td className="numeric">{summary.win_rate_pct.toFixed(1)}%</td>
      <td className="numeric">
        {summary.profit_factor === null ? "-" : summary.profit_factor.toFixed(2)}
      </td>
      <td className="numeric">{formatPercent(-summary.max_drawdown_pct)}</td>
      <td className="numeric">{formatCurrency(summary.expectancy)}</td>
      <td className="numeric">{summary.max_consecutive_losses}</td>
      <td className="numeric muted">{formatCurrency(summary.fees + summary.funding)}</td>
    </tr>
  );
}

export function ComparisonPage() {
  const [mode, setMode] = useState("paper");
  const { data, isLoading, error } = usePolledQuery(
    ["comparison", mode],
    () => strategyService.comparison(mode),
    REFRESH_SLOW,
  );

  if (isLoading && !data) {
    return <Loading />;
  }
  if (error) {
    return <ErrorState error={error} />;
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Strategy comparison</h1>
          <p>
            Side by side performance per strategy and per market. Small sample sizes are
            noise: treat fewer than 30 trades as no information at all.
          </p>
        </div>
        <div className="field" style={{ minWidth: 160 }}>
          <label htmlFor="cmp-mode">Mode</label>
          <select id="cmp-mode" value={mode} onChange={(event) => setMode(event.target.value)}>
            {MODES.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </div>
      </div>

      <Panel title="Overall" subtitle={"Trading mode: " + mode}>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Strategy</th>
                <th className="numeric">Trades</th>
                <th className="numeric">Net PnL</th>
                <th className="numeric">Win rate</th>
                <th className="numeric">Profit factor</th>
                <th className="numeric">Max DD</th>
                <th className="numeric">Expectancy</th>
                <th className="numeric">Max losses</th>
                <th className="numeric">Costs</th>
              </tr>
            </thead>
            <tbody>
              {(data?.rows ?? []).map((row) => (
                <MetricRow key={row.strategy} label={row.strategy} summary={row.overall} />
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {(data?.symbols ?? []).map((symbol) => (
        <Panel key={symbol} title={symbol}>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Strategy</th>
                  <th className="numeric">Trades</th>
                  <th className="numeric">Net PnL</th>
                  <th className="numeric">Win rate</th>
                  <th className="numeric">Profit factor</th>
                  <th className="numeric">Max DD</th>
                  <th className="numeric">Expectancy</th>
                  <th className="numeric">Max losses</th>
                  <th className="numeric">Costs</th>
                </tr>
              </thead>
              <tbody>
                {(data?.rows ?? []).map((row) => {
                  const entry = row.by_symbol.find((item) => item.symbol === symbol);
                  if (!entry) {
                    return null;
                  }
                  return <MetricRow key={row.strategy + symbol} label={row.strategy} summary={entry} />;
                })}
              </tbody>
            </table>
          </div>
        </Panel>
      ))}

      <div className="disclaimer">
        Comparing strategies on live or paper results with few trades tells you almost
        nothing. Use the Backtest Lab with walk-forward analysis for a more honest picture,
        and remember that even that is not a prediction.
      </div>
    </>
  );
}
