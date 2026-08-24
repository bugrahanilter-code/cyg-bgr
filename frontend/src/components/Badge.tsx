import type { ReactNode } from "react";

import type { BadgeTone } from "@/utils/tone";

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
