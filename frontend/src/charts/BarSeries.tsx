export interface BarPoint {
  label: string;
  value: number;
}

interface BarSeriesProps {
  points: BarPoint[];
  height?: number;
  suffix?: string;
  positiveColor?: string;
  negativeColor?: string;
}

/**
 * Dependency-free bar chart used for monthly returns and trade
 * distributions. Values may be negative; the zero line stays centred.
 */
export function BarSeries({
  points,
  height = 180,
  suffix = "",
  positiveColor = "#2ecc8f",
  negativeColor = "#ff5c6c",
}: BarSeriesProps) {
  if (points.length === 0) {
    return <div className="table-empty">No data yet.</div>;
  }

  const maxAbsolute = Math.max(...points.map((point) => Math.abs(point.value)), 1);
  const hasNegative = points.some((point) => point.value < 0);
  const zeroLine = hasNegative ? height / 2 : height - 18;
  const usableHeight = hasNegative ? height / 2 - 10 : height - 28;

  return (
    <div style={{ width: "100%", overflowX: "auto" }}>
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          gap: 6,
          height,
          minWidth: points.length * 34,
          position: "relative",
        }}
      >
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: zeroLine,
            borderTop: "1px dashed var(--border-strong)",
          }}
        />
        {points.map((point) => {
          const magnitude = (Math.abs(point.value) / maxAbsolute) * usableHeight;
          const isPositive = point.value >= 0;
          return (
            <div
              key={point.label}
              style={{
                flex: 1,
                minWidth: 26,
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "flex-end",
                height: "100%",
                position: "relative",
              }}
              title={point.label + ": " + point.value.toFixed(2) + suffix}
            >
              <div
                style={{
                  position: "absolute",
                  top: isPositive ? zeroLine - magnitude : zeroLine,
                  height: Math.max(magnitude, 2),
                  width: "70%",
                  background: isPositive ? positiveColor : negativeColor,
                  borderRadius: 3,
                  opacity: 0.85,
                }}
              />
              <span
                style={{
                  position: "absolute",
                  bottom: -2,
                  fontSize: 9.5,
                  color: "var(--text-dim)",
                  whiteSpace: "nowrap",
                  transform: "rotate(-35deg)",
                  transformOrigin: "center",
                }}
              >
                {point.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
