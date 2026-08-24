import { useEffect, useRef } from "react";
import { ColorType, createChart } from "lightweight-charts";
import type { IChartApi, UTCTimestamp } from "lightweight-charts";

import { parseUtc } from "@/utils/format";

export interface SeriesPoint {
  time: string | number;
  value: number;
}

interface LineAreaChartProps {
  data: SeriesPoint[];
  color?: string;
  area?: boolean;
  height?: number;
  priceFormat?: "price" | "percent";
  baseline?: number;
}

function toTimestamp(value: string | number): UTCTimestamp {
  if (typeof value === "number") {
    return (value > 1e12 ? Math.floor(value / 1000) : Math.floor(value)) as UTCTimestamp;
  }
  const parsed = parseUtc(value);
  return Math.floor((parsed ? parsed.getTime() : Date.now()) / 1000) as UTCTimestamp;
}

/**
 * Reusable TradingView Lightweight Chart.
 *
 * The component is presentation only: it receives already computed points and
 * never fetches or transforms trading data itself.
 */
export function LineAreaChart({
  data,
  color = "#4c8dff",
  area = true,
  height = 280,
  priceFormat = "price",
}: LineAreaChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);

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
        vertLines: { color: "rgba(35, 44, 64, 0.6)" },
        horzLines: { color: "rgba(35, 44, 64, 0.6)" },
      },
      rightPriceScale: { borderColor: "#232c40" },
      timeScale: { borderColor: "#232c40", timeVisible: true, secondsVisible: false },
      crosshair: { mode: 0 },
      handleScale: true,
      handleScroll: true,
    });
    chartRef.current = chart;

    const series = area
      ? chart.addAreaSeries({
          lineColor: color,
          topColor: color + "55",
          bottomColor: color + "05",
          lineWidth: 2,
          priceFormat:
            priceFormat === "percent"
              ? { type: "custom", formatter: (price: number) => price.toFixed(2) + "%" }
              : { type: "price", precision: 2, minMove: 0.01 },
        })
      : chart.addLineSeries({
          color,
          lineWidth: 2,
          priceFormat:
            priceFormat === "percent"
              ? { type: "custom", formatter: (price: number) => price.toFixed(2) + "%" }
              : { type: "price", precision: 2, minMove: 0.01 },
        });

    const points = data
      .map((point) => ({ time: toTimestamp(point.time), value: Number(point.value) }))
      .filter((point) => Number.isFinite(point.value))
      .sort((left, right) => (left.time as number) - (right.time as number));

    const unique: typeof points = [];
    points.forEach((point) => {
      const last = unique[unique.length - 1];
      if (last && last.time === point.time) {
        unique[unique.length - 1] = point;
      } else {
        unique.push(point);
      }
    });

    series.setData(unique);
    chart.timeScale().fitContent();

    const observer = new ResizeObserver(() => {
      chart.applyOptions({ width: container.clientWidth });
    });
    observer.observe(container);
    chart.applyOptions({ width: container.clientWidth });

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [data, color, area, height, priceFormat]);

  return <div ref={containerRef} className="chart-container" style={{ height }} />;
}
