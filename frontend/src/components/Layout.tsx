import { NavLink, Outlet } from "react-router-dom";

import { Badge, StatusDot } from "@/components/Badge";
import { Modal } from "@/components/Modal";
import { EmergencyStopPanel } from "@/components/EmergencyStopPanel";
import { Toasts } from "@/components/Toasts";
import { REFRESH_FAST, useApiMutation, usePolledQuery } from "@/hooks/useApi";
import { systemService } from "@/services/tradingService";
import { useAppState } from "@/state/appStateContext";
import { formatAgo } from "@/utils/format";
import { useState } from "react";

const NAV_ITEMS = [
  { to: "/", label: "Overview", icon: "OV", end: true },
  { to: "/positions", label: "Positions", icon: "PO" },
  { to: "/trades", label: "Trades", icon: "TR" },
  { to: "/strategies", label: "Strategies", icon: "ST" },
  { to: "/comparison", label: "Comparison", icon: "CM" },
  { to: "/backtest", label: "Backtest Lab", icon: "BT" },
  { to: "/risk", label: "Risk Settings", icon: "RK" },
  { to: "/system", label: "System", icon: "SY" },
  { to: "/settings", label: "Settings", icon: "SE" },
];

function modeTone(mode: string) {
  if (mode === "live") return "danger" as const;
  if (mode === "paper") return "info" as const;
  return "neutral" as const;
}

/** Application frame: navigation, status bar and the emergency stop. */
export function Layout() {
  const [stopOpen, setStopOpen] = useState(false);
  const status = usePolledQuery(["system-status"], systemService.status, REFRESH_FAST);
  const { pushToast } = useAppState();

  const startEngine = useApiMutation(
    () => systemService.startEngine(),
    [["system-status"], ["health"], ["overview"]],
    {
      onSuccess: (response) => pushToast(response.message, response.ok ? "success" : "error"),
      onError: (error) => pushToast(error.message, "error"),
    },
  );
  const stopEngine = useApiMutation(
    () => systemService.stopEngine(),
    [["system-status"], ["health"], ["overview"]],
    {
      onSuccess: (response) => pushToast(response.message, "success"),
      onError: (error) => pushToast(error.message, "error"),
    },
  );

  const bot = status.data;
  const engineRunning = Boolean(
    bot?.engine && (bot.engine as { running?: boolean }).running,
  );

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <strong>Crypto Trading</strong>
          <span>Local platform</span>
        </div>
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}
          >
            <span className="nav-icon">{item.icon}</span>
            {item.label}
          </NavLink>
        ))}
        <div className="spacer" />
        <div className="disclaimer" style={{ padding: "0 10px" }}>
          This software gives no profit guarantee. Trade at your own risk.
        </div>
      </aside>

      <div className="main-area">
        <header className="topbar">
          <div className="topbar-group">
            <Badge tone={modeTone(bot?.mode ?? "paper")}>
              {(bot?.mode ?? "paper").toUpperCase()} MODE
            </Badge>
            <span className="row small">
              <StatusDot status={engineRunning ? "OK" : "DOWN"} />
              Engine {engineRunning ? "running" : "stopped"}
            </span>
            <span className="row small">
              <StatusDot status={bot?.reconciliation_status ?? "UNKNOWN"} />
              Reconciliation
            </span>
            <span className="small muted">
              Heartbeat {formatAgo(bot?.last_heartbeat ?? null)}
            </span>
          </div>

          <div className="topbar-group">
            {bot?.emergency_stop_level && bot.emergency_stop_level !== "NONE" && (
              <Badge tone="danger">STOP: {bot.emergency_stop_level}</Badge>
            )}
            {bot?.live_trading_confirmed && <Badge tone="danger">LIVE ORDERS ENABLED</Badge>}
            {engineRunning ? (
              <button
                type="button"
                className="btn btn-sm"
                disabled={stopEngine.isPending}
                onClick={() => stopEngine.mutate(undefined)}
                title="Stops the trading engine. Open positions are left untouched."
              >
                {stopEngine.isPending ? "Stopping..." : "STOP BOT"}
              </button>
            ) : (
              <button
                type="button"
                className="btn btn-success btn-sm"
                disabled={startEngine.isPending}
                onClick={() => startEngine.mutate(undefined)}
                title="Starts the trading engine in the current mode."
              >
                {startEngine.isPending ? "Starting..." : "START BOT"}
              </button>
            )}
            <button
              type="button"
              className="btn btn-danger btn-sm"
              onClick={() => setStopOpen(true)}
            >
              EMERGENCY STOP
            </button>
          </div>
        </header>

        <main className="page">
          <Outlet />
        </main>
      </div>

      <Modal open={stopOpen} title="Emergency stop" onClose={() => setStopOpen(false)}>
        <EmergencyStopPanel currentLevel={bot?.emergency_stop_level ?? "NONE"} />
      </Modal>

      <Toasts />
    </div>
  );
}
