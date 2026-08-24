import type { ReactNode } from "react";

interface StatCardProps {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "neutral" | "positive" | "negative" | "warning";
}

/** Single headline number with an optional secondary line. */
export function StatCard({ label, value, hint, tone = "neutral" }: StatCardProps) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className={"stat-value " + tone}>{value}</div>
      {hint !== undefined && <div className="stat-hint">{hint}</div>}
    </div>
  );
}
