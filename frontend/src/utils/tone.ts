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
