import { useEffect, useState } from "react";

import { Badge } from "@/components/Badge";
import { Panel } from "@/components/Panel";
import { ParamsForm } from "@/components/ParamsForm";
import { ErrorState, Loading } from "@/components/StateViews";
import { Toggle } from "@/components/Toggle";
import { REFRESH_NORMAL, useApiMutation, usePolledQuery } from "@/hooks/useApi";
import { strategyService } from "@/services/tradingService";
import { useAppState } from "@/state/appStateContext";
import type { StrategySummary } from "@/types/api";
import { formatCurrency, formatPercent, formatPrice, formatSignedCurrency, pnlClass } from "@/utils/format";
import { RISK_LEVEL_HELP, RISK_LEVEL_LABEL, riskTone, signalTone } from "@/utils/tone";

function StrategyCard({ strategy }: { strategy: StrategySummary }) {
  const { pushToast } = useAppState();
  const [params, setParams] = useState<Record<string, unknown>>(strategy.params);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (!dirty) {
      setParams(strategy.params);
    }
  }, [strategy.params, dirty]);

  const update = useApiMutation(
    (payload: { enabled?: boolean; params?: Record<string, unknown> }) =>
      strategyService.update(strategy.key, payload),
    [["strategies"], ["overview"]],
    {
      onSuccess: (response) => {
        pushToast(response.message, "success");
        setDirty(false);
      },
      onError: (error) => pushToast(error.message, "error"),
    },
  );

  const reset = useApiMutation(
    () => strategyService.resetParams(strategy.key),
    [["strategies"]],
    {
      onSuccess: () => {
        pushToast("Default parameters restored", "success");
        setDirty(false);
      },
    },
  );

  const performance = strategy.performance;
  const signal = strategy.current_signal;

  return (
    <Panel
      title={strategy.name}
      subtitle={strategy.description}
      actions={
        <div className="row">
          <span title={RISK_LEVEL_HELP[strategy.risk_level]}>
            <Badge tone={riskTone(strategy.risk_level)}>
              {RISK_LEVEL_LABEL[strategy.risk_level]}
            </Badge>
          </span>
          <Toggle
            checked={strategy.enabled}
            label={strategy.enabled ? "Enabled" : "Disabled"}
            disabled={update.isPending}
            onChange={(value) => update.mutate({ enabled: value })}
          />
        </div>
      }
    >
      <div className="grid grid-4">
        <div className="stat-card">
          <div className="stat-label">Current signal</div>
          <div className="stat-value" style={{ fontSize: 16 }}>
            {signal ? <Badge tone={signalTone(signal.signal)}>{signal.signal}</Badge> : "-"}
          </div>
          <div className="stat-hint">
            {signal ? "Confidence " + (signal.confidence * 100).toFixed(0) + "%" : "Waiting for a candle"}
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Market regime</div>
          <div className="stat-value" style={{ fontSize: 14 }}>
            {signal?.regime?.regime ?? "UNKNOWN"}
          </div>
          <div className="stat-hint">
            {signal?.regime ? "ADX " + (signal.regime.adx ?? 0).toFixed(1) : ""}
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Net PnL</div>
          <div className={"stat-value " + pnlClass(performance.net_pnl)} style={{ fontSize: 18 }}>
            {formatSignedCurrency(performance.net_pnl)}
          </div>
          <div className="stat-hint">{performance.trades} trades</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Win rate</div>
          <div className="stat-value" style={{ fontSize: 18 }}>
            {performance.win_rate_pct.toFixed(1)}%
          </div>
          <div className="stat-hint">
            PF {performance.profit_factor === null ? "-" : performance.profit_factor.toFixed(2)} |
            DD {performance.max_drawdown_pct.toFixed(1)}%
          </div>
        </div>
      </div>

      {signal && (
        <div className="banner banner-info">
          <div>
            <strong>{signal.symbol}</strong> - {signal.explanation}
            {signal.entry !== null && (
              <div className="small">
                Entry {formatPrice(signal.entry)} | Stop {formatPrice(signal.stop_loss)} | Target{" "}
                {formatPrice(signal.take_profit)}
              </div>
            )}
          </div>
        </div>
      )}

      <details>
        <summary className="small muted" style={{ cursor: "pointer", padding: "6px 0" }}>
          Parameters
        </summary>
        <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 12 }}>
          <ParamsForm
            schema={strategy.param_schema}
            values={params}
            disabled={update.isPending}
            onChange={(key, value) => {
              setDirty(true);
              setParams((current) => ({ ...current, [key]: value }));
            }}
          />
          <div className="btn-row">
            <button
              type="button"
              className="btn btn-primary"
              disabled={!dirty || update.isPending}
              onClick={() => update.mutate({ params })}
            >
              Save parameters
            </button>
            <button
              type="button"
              className="btn"
              disabled={reset.isPending}
              onClick={() => reset.mutate(undefined)}
            >
              Restore defaults
            </button>
          </div>
          <small className="muted">
            Changing parameters affects future signals only. Validate a change with a backtest
            and with paper trading before using it live.
          </small>
        </div>
      </details>

      <div className="grid grid-4 small">
        <div className="definition">
          <span>Expectancy</span>
          <span>{formatCurrency(performance.expectancy)}</span>
        </div>
        <div className="definition">
          <span>Average win</span>
          <span>{formatCurrency(performance.average_win)}</span>
        </div>
        <div className="definition">
          <span>Average loss</span>
          <span>{formatCurrency(performance.average_loss)}</span>
        </div>
        <div className="definition">
          <span>Average return</span>
          <span>{formatPercent(performance.average_return_pct)}</span>
        </div>
      </div>
    </Panel>
  );
}

export function StrategiesPage() {
  const { data, isLoading, error } = usePolledQuery(
    ["strategies"],
    strategyService.list,
    REFRESH_NORMAL,
  );

  const strategies = data ?? [];

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
          <h1>Strategies</h1>
          <p>
            Thirteen independent, publicly documented systematic families, grouped by how
            aggressive they are. Each one can be turned on or off separately and each one
            documents the conditions in which it loses money.
          </p>
        </div>
        <div className="row">
          {(["safe", "medium", "risky"] as const).map((level) => (
            <span key={level} title={RISK_LEVEL_HELP[level]}>
              <Badge tone={riskTone(level)}>
                {RISK_LEVEL_LABEL[level]} {strategies.filter((s) => s.risk_level === level).length}
              </Badge>
            </span>
          ))}
        </div>
      </div>

      {(["safe", "medium", "risky"] as const).map((level) => {
        const group = strategies.filter((strategy) => strategy.risk_level === level);
        if (group.length === 0) {
          return null;
        }
        return (
          <div key={level} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <div className="row" style={{ marginTop: 6 }}>
              <Badge tone={riskTone(level)}>{RISK_LEVEL_LABEL[level]}</Badge>
              <span className="small muted">{RISK_LEVEL_HELP[level]}</span>
            </div>
            {group.map((strategy) => (
              <StrategyCard key={strategy.key} strategy={strategy} />
            ))}
          </div>
        );
      })}

      <div className="disclaimer">
        No strategy in this platform is guaranteed to be profitable. Read
        docs/strategies for the assumptions, the known failure modes and the transaction cost
        sensitivity of each family.
      </div>
    </>
  );
}
