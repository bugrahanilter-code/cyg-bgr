interface ProgressBarProps {
  value: number;
  max?: number;
  tone?: "accent" | "positive" | "negative" | "warning";
  leftLabel?: string;
  rightLabel?: string;
}

const COLORS: Record<string, string> = {
  accent: "var(--accent)",
  positive: "var(--positive)",
  negative: "var(--negative)",
  warning: "var(--warning)",
};

/** Horizontal progress indicator used for daily targets and limits. */
export function ProgressBar({
  value,
  max = 100,
  tone = "accent",
  leftLabel,
  rightLabel,
}: ProgressBarProps) {
  const safeMax = max === 0 ? 1 : max;
  const percent = Math.max(0, Math.min(100, (value / safeMax) * 100));
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
      <div className="progress">
        <div
          className="progress-fill"
          style={{ width: percent + "%", background: COLORS[tone] }}
        />
      </div>
      {(leftLabel || rightLabel) && (
        <div className="progress-labels">
          <span>{leftLabel}</span>
          <span>{rightLabel}</span>
        </div>
      )}
    </div>
  );
}
