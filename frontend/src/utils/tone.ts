/**
 * Colour tone helpers.
 *
 * They live outside the component files so those files export components only,
 * which keeps React Fast Refresh working during development.
 */

export type BadgeTone = "neutral" | "success" | "danger" | "warning" | "info";

/** Long positions are green, short positions are red. */
export function sideTone(side: string): BadgeTone {
  return side.toUpperCase() === "LONG" ? "success" : "danger";
}

/** Colour for a strategy signal. */
export function signalTone(signal: string): BadgeTone {
  const value = signal.toUpperCase();
  if (value === "LONG") return "success";
  if (value === "SHORT") return "danger";
  if (value === "CLOSE") return "warning";
  return "neutral";
}

/** Colour for a system event severity. */
export function severityTone(severity: string): BadgeTone {
  const value = severity.toUpperCase();
  if (value === "CRITICAL" || value === "ERROR") return "danger";
  if (value === "WARNING") return "warning";
  return "neutral";
}

/** Colour for a strategy risk level. */
export function riskTone(level: string): BadgeTone {
  if (level === "safe") return "success";
  if (level === "risky") return "danger";
  return "warning";
}

/** Short plain-language explanation of a risk level. */
export const RISK_LEVEL_HELP: Record<string, string> = {
  safe: "Few trades, wide stops, trades with the trend. Slow and usually long-only.",
  medium: "Standard systematic approach with trend and strength filters.",
  risky: "Counter-trend, high frequency or direction-agnostic. Expect more losing trades.",
};

export const RISK_LEVEL_LABEL: Record<string, string> = {
  safe: "SAFE",
  medium: "MEDIUM",
  risky: "RISKY",
};
