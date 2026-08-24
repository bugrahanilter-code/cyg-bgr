import type { ReactNode } from "react";

export type BadgeTone = "neutral" | "success" | "danger" | "warning" | "info";

export function Badge({ tone = "neutral", children }: { tone?: BadgeTone; children: ReactNode }) {
  return <span className={"badge badge-" + tone}>{children}</span>;
}

export function StatusDot({ status }: { status: string }) {
  const normalised = (status || "UNKNOWN").toUpperCase();
  const className =
    normalised === "OK" || normalised === "CONNECTED" || normalised === "IN_SYNC"
      ? "dot-ok"
      : normalised === "DEGRADED" || normalised === "CONNECTING" || normalised === "NEVER_RUN"
        ? "dot-degraded"
        : normalised === "UNKNOWN"
          ? "dot-unknown"
          : "dot-down";
  return <span className={"status-dot " + className} title={normalised} />;
}

export function sideTone(side: string): BadgeTone {
  return side.toUpperCase() === "LONG" ? "success" : "danger";
}

export function signalTone(signal: string): BadgeTone {
  const value = signal.toUpperCase();
  if (value === "LONG") return "success";
  if (value === "SHORT") return "danger";
  if (value === "CLOSE") return "warning";
  return "neutral";
}
