import { useEffect, useRef } from "react";

interface TradingViewChartProps {
  /** TradingView ticker, e.g. `BINANCE:BTCUSDT.P`. */
  symbol: string;
  interval?: string;
  height?: number;
  theme?: "dark" | "light";
}

/**
 * TradingView's free "Advanced Chart" widget.
 *
 * This renders TradingView's own data inside their iframe. It is a *view*, not
 * a data source: nothing the widget shows is read back into the platform, and
 * every backtest still runs on the candles this backend downloaded from
 * Binance. That distinction matters, because a chart that quietly disagrees
 * with the backtester is worse than no chart at all.
 *
 * The script is injected per instance and removed on unmount, which is what the
 * widget expects when the symbol changes.
 */
export function TradingViewChart({
  symbol,
  interval = "60",
  height = 480,
  theme = "dark",
}: TradingViewChartProps) {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = container.current;
    if (!node) {
      return;
    }
    node.innerHTML = "";

    const holder = document.createElement("div");
    holder.className = "tradingview-widget-container__widget";
    holder.style.height = height + "px";
    node.appendChild(holder);

    const script = document.createElement("script");
    script.src =
      "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    script.type = "text/javascript";
    script.async = true;
    script.innerHTML = JSON.stringify({
      autosize: false,
      width: "100%",
      height,
      symbol,
      interval,
      timezone: "Etc/UTC",
      theme,
      style: "1",
      locale: "en",
      enable_publishing: false,
      allow_symbol_change: false,
      hide_side_toolbar: false,
      withdateranges: true,
      studies: ["STD;EMA", "STD;RSI"],
      support_host: "https://www.tradingview.com",
    });
    node.appendChild(script);

    return () => {
      node.innerHTML = "";
    };
  }, [symbol, interval, height, theme]);

  return (
    <div className="tradingview-widget-container" ref={container} style={{ height }}>
      <div className="chart-fallback">
        Loading the TradingView chart for {symbol}. If it stays empty, the browser
        is blocking third-party scripts.
      </div>
    </div>
  );
}
