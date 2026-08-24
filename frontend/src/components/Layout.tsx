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

/**
 * Nine destinations grouped into three. A flat list of nine is a wall; three
 * groups of three are scannable, and the grouping itself explains what the
 * platform does: watch it, shape it, configure it.
 */
const NAV_GROUPS = [
  {
    label: "İzle",
    items: [
      { to: "/", label: "Genel Bakış", icon: "◎", end: true },
      { to: "/markets", label: "Piyasalar", icon: "◈" },
      { to: "/trades", label: "İşlemler", icon: "⇄" },
    ],
  },
  {
    label: "Strateji",
    items: [
      { to: "/strategies", label: "Stratejiler", icon: "◇" },
      { to: "/backtest", label: "Test", icon: "◔" },
      { to: "/rotation", label: "Otomasyon", icon: "⟳" },
    ],
  },
  {
    label: "Yönet",
    items: [
      { to: "/risk", label: "Risk", icon: "△" },
      { to: "/system", label: "Sistem", icon: "◍" },
      { to: "/settings", label: "Ayarlar", icon: "⚙" },
    ],
  },
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
          <strong>Kripto Terminal</strong>
          <span>Yerel platform</span>
        </div>
        {NAV_GROUPS.map((group) => (
          <div key={group.label}>
            <div className="nav-group">{group.label}</div>
            {group.items.map((item) => (
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
          </div>
        ))}
        <div className="spacer" />
        <div className="disclaimer" style={{ padding: "0 10px" }}>
          Bu yazılım kâr garantisi vermez. Sorumluluk size aittir.
        </div>
      </aside>

      <div className="main-area">
        <header className="topbar">
          <div className="topbar-group">
            <Badge tone={modeTone(bot?.mode ?? "paper")}>
              {bot?.mode === "live" ? "GERÇEK PARA" : "KAĞIT"}
            </Badge>
            <span className="row small">
              <StatusDot status={engineRunning ? "OK" : "DOWN"} />
              {engineRunning ? "Motor çalışıyor" : "Motor durdu"}
            </span>
            <span className="row small">
              <StatusDot status={bot?.reconciliation_status ?? "UNKNOWN"} />
              Mutabakat
            </span>
            <span className="small muted">
              Son sinyal {formatAgo(bot?.last_heartbeat ?? null)}
            </span>
          </div>

          <div className="topbar-group">
            {bot?.emergency_stop_level && bot.emergency_stop_level !== "NONE" && (
              <Badge tone="danger">DURDURULDU</Badge>
            )}
            {bot?.live_trading_confirmed && <Badge tone="danger">GERÇEK EMİR AÇIK</Badge>}
            {engineRunning ? (
              <button
                type="button"
                className="btn btn-sm"
                disabled={stopEngine.isPending}
                onClick={() => stopEngine.mutate(undefined)}
                title="Motoru durdurur. Açık pozisyonlara dokunulmaz."
              >
                {stopEngine.isPending ? "Durduruluyor…" : "Durdur"}
              </button>
            ) : (
              <button
                type="button"
                className="btn btn-success btn-sm"
                disabled={startEngine.isPending}
                onClick={() => startEngine.mutate(undefined)}
                title="Motoru mevcut modda başlatır."
              >
                {startEngine.isPending ? "Başlatılıyor…" : "Başlat"}
              </button>
            )}
            <button
              type="button"
              className="btn btn-danger btn-sm"
              onClick={() => setStopOpen(true)}
            >
              Acil Durdur
            </button>
          </div>
        </header>

        <main className="page">
          <Outlet />
        </main>
      </div>

      <Modal open={stopOpen} title="Acil durdurma" onClose={() => setStopOpen(false)}>
        <EmergencyStopPanel currentLevel={bot?.emergency_stop_level ?? "NONE"} />
      </Modal>

      <Toasts />
    </div>
  );
}
