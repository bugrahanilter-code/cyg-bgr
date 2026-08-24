import { Badge, StatusDot } from "@/components/Badge";
import { Panel } from "@/components/Panel";
import { Banner, ErrorState, Loading } from "@/components/StateViews";
import { REFRESH_FAST, REFRESH_NORMAL, useApiMutation, usePolledQuery } from "@/hooks/useApi";
import { systemService } from "@/services/tradingService";
import { useAppState } from "@/state/AppState";
import { formatAgo, formatDateTime } from "@/utils/format";

function severityTone(severity: string) {
  if (severity === "CRITICAL" || severity === "ERROR") return "danger" as const;
  if (severity === "WARNING") return "warning" as const;
  return "neutral" as const;
}

export function SystemMonitorPage() {
  const { pushToast } = useAppState();
  const health = usePolledQuery(["health"], systemService.health, REFRESH_FAST);
  const events = usePolledQuery(
    ["events"],
    () => systemService.events(80),
    REFRESH_NORMAL,
  );

  const start = useApiMutation(() => systemService.startEngine(), [["health"], ["system-status"]], {
    onSuccess: (response) => pushToast(response.message, response.ok ? "success" : "error"),
    onError: (error) => pushToast(error.message, "error"),
  });
  const stop = useApiMutation(() => systemService.stopEngine(), [["health"], ["system-status"]], {
    onSuccess: (response) => pushToast(response.message, "success"),
  });

  if (health.isLoading && !health.data) {
    return <Loading />;
  }
  if (health.error) {
    return <ErrorState error={health.error} hint="The backend may be down." />;
  }

  const report = health.data;
  const engineRunning = Boolean((report?.engine as { running?: boolean })?.running);

  return (
    <>
      <div className="page-header">
        <div>
          <h1>System monitoring</h1>
          <p>Health of every component, the heartbeat and the structured event log.</p>
        </div>
        <div className="btn-row">
          <button
            type="button"
            className="btn btn-success"
            disabled={engineRunning || start.isPending}
            onClick={() => start.mutate(undefined)}
          >
            Start engine
          </button>
          <button
            type="button"
            className="btn"
            disabled={!engineRunning || stop.isPending}
            onClick={() => stop.mutate(undefined)}
          >
            Stop engine
          </button>
        </div>
      </div>

      {report?.overall !== "OK" && (
        <Banner tone={report?.overall === "DOWN" ? "danger" : "warning"}>
          Overall system status: {report?.overall}. New trades are only allowed when the market
          data, the exchange connection and the reconciliation are healthy.
        </Banner>
      )}

      <div className="grid grid-3">
        {(report?.components ?? []).map((component) => (
          <div className="stat-card" key={component.name}>
            <div className="row-between">
              <span className="stat-label">{component.name}</span>
              <StatusDot status={component.status} />
            </div>
            <div className="stat-value" style={{ fontSize: 15 }}>
              {component.status}
            </div>
            <div className="stat-hint">{component.detail}</div>
          </div>
        ))}
      </div>

      <Panel title="Engine">
        <div className="grid grid-3">
          <div className="definition">
            <span>Status</span>
            <span>{report?.bot_status}</span>
          </div>
          <div className="definition">
            <span>Mode</span>
            <span>{report?.mode}</span>
          </div>
          <div className="definition">
            <span>Emergency stop</span>
            <span>{report?.emergency_stop_level}</span>
          </div>
          <div className="definition">
            <span>Live orders</span>
            <span>{report?.live_trading_confirmed ? "ENABLED" : "disabled"}</span>
          </div>
          <div className="definition">
            <span>Last heartbeat</span>
            <span>{formatAgo(report?.last_heartbeat ?? null)}</span>
          </div>
          <div className="definition">
            <span>Last market data</span>
            <span>{formatAgo(report?.last_market_data ?? null)}</span>
          </div>
        </div>
        <pre
          className="small mono"
          style={{
            background: "var(--bg)",
            padding: 12,
            borderRadius: 6,
            overflowX: "auto",
            margin: 0,
          }}
        >
          {JSON.stringify(report?.engine ?? {}, null, 2)}
        </pre>
      </Panel>

      <Panel title="Event log" subtitle="Signals, orders, risk rejections, reconciliation and errors">
        <div className="table-wrap" style={{ maxHeight: 460, overflowY: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Severity</th>
                <th>Category</th>
                <th>Message</th>
                <th>Symbol</th>
              </tr>
            </thead>
            <tbody>
              {(events.data ?? []).length === 0 && (
                <tr>
                  <td colSpan={5} className="table-empty">
                    No events recorded yet.
                  </td>
                </tr>
              )}
              {(events.data ?? []).map((event) => (
                <tr key={event.id}>
                  <td>{formatDateTime(event.created_at)}</td>
                  <td>
                    <Badge tone={severityTone(event.severity)}>{event.severity}</Badge>
                  </td>
                  <td className="small">{event.category}</td>
                  <td style={{ whiteSpace: "normal" }}>{event.message}</td>
                  <td className="small">{event.symbol}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  );
}
