import { useEffect, useRef } from "react";
import { ColorType, createChart } from "lightweight-charts";
import type { UTCTimestamp } from "lightweight-charts";

import type { Candle } from "@/types/api";

interface CandleChartProps {
  candles: Candle[];
  height?: number;
}

/** Price chart for a market, driven entirely by backend data. */
export function CandleChart({ candles, height = 320 }: CandleChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }
    const chart = createChart(container, {
      height,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#97a3b8",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "rgba(35, 44, 64, 0.5)" },
        horzLines: { color: "rgba(35, 44, 64, 0.5)" },
      },
      rightPriceScale: { borderColor: "#232c40" },
      timeScale: { borderColor: "#232c40", timeVisible: true, secondsVisible: false },
    });

    const series = chart.addCandlestickSeries({
      upColor: "#2ecc8f",
      downColor: "#ff5c6c",
      borderUpColor: "#2ecc8f",
      borderDownColor: "#ff5c6c",
      wickUpColor: "#2ecc8f",
      wickDownColor: "#ff5c6c",
    });

    series.setData(
      candles
        .slice()
        .sort((left, right) => left.open_time - right.open_time)
        .map((candle) => ({
          time: Math.floor(candle.open_time / 1000) as UTCTimestamp,
          open: candle.open,
          high: candle.high,
          low: candle.low,
          close: candle.close,
        })),
    );
    chart.timeScale().fitContent();

    const observer = new ResizeObserver(() => {
      chart.applyOptions({ width: container.clientWidth });
    });
    observer.observe(container);
    chart.applyOptions({ width: container.clientWidth });

    return () => {
      observer.disconnect();
      chart.remove();
    };
  }, [candles, height]);

  return <div ref={containerRef} className="chart-container" style={{ height }} />;
}
