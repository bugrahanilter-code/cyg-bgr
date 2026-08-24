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
      <Panel
        title="Genel"
        actions={
          <select value={mode} onChange={(event) => setMode(event.target.value)}>
            {MODES.map((item) => (
              <option key={item} value={item}>
                {item === "paper" ? "Kağıt" : item === "live" ? "Gerçek" : "Backtest"}
              </option>
            ))}
          </select>
        }
      >
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Strateji</th>
                <th className="numeric">İşlem</th>
                <th className="numeric">Net K/Z</th>
                <th className="numeric">Kazanma</th>
                <th className="numeric">Kâr faktörü</th>
                <th className="numeric">Maks. düşüş</th>
                <th className="numeric">Beklenti</th>
                <th className="numeric">Üst üste zarar</th>
                <th className="numeric">Maliyet</th>
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
                  <th>Strateji</th>
                  <th className="numeric">İşlem</th>
                  <th className="numeric">Net K/Z</th>
                  <th className="numeric">Kazanma</th>
                  <th className="numeric">Kâr faktörü</th>
                  <th className="numeric">Maks. düşüş</th>
                  <th className="numeric">Beklenti</th>
                  <th className="numeric">Üst üste zarar</th>
                  <th className="numeric">Maliyet</th>
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
