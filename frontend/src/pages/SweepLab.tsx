import { useMemo, useState } from "react";

import { Badge } from "@/components/Badge";
import { Panel } from "@/components/Panel";
import { ProgressBar } from "@/components/ProgressBar";
import { Banner, ErrorState, Loading } from "@/components/StateViews";
import { REFRESH_FAST, REFRESH_SLOW, useApiMutation, useOnceQuery, usePolledQuery } from "@/hooks/useApi";
import { sweepService } from "@/services/tradingService";
import type { SweepPayload } from "@/services/tradingService";
import { useAppState } from "@/state/appStateContext";
import type { SweepEstimate, SweepMatrixCell, SweepView } from "@/types/api";
import {
  daysAgoIso,
  formatDuration,
  formatNumber,
  parseUtc,
  pnlClass,
  toIsoDate,
} from "@/utils/format";

const ALL_TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w"];
const DEFAULT_TIMEFRAMES = ["15m", "30m", "1h", "2h", "4h", "1d"];

const SYMBOL_SOURCES: Array<{ value: string; label: string; hint: string }> = [
  { value: "top_volume", label: "Hacme göre en büyük marketler", hint: "Binance'ten canlı sıralanır" },
  { value: "enabled", label: "İşleme açık marketler", hint: "Botun bugün işlediği marketler" },
  { value: "database", label: "Aktarılmış tüm marketler", hint: "Yerel veritabanındaki her şey" },
  { value: "all", label: "Binance'teki tüm marketler", hint: "Tüm USDT perpetualler, ~525" },
];

const METRICS: Array<{ value: string; label: string; help: string }> = [
  {
    value: "expectancy_r",
    label: "Beklenti (işlem başına R)",
    help: "Risk birimi cinsinden işlem başına ortalama kâr. Sıfırın üstü, edge maliyeti aştı demektir.",
  },
  { value: "sharpe_ratio", label: "Sharpe oranı", help: "Oynaklık birimi başına getiri." },
  { value: "return_pct", label: "Toplam getiri %", help: "Dönem boyunca ham hesap getirisi." },
  { value: "profit_factor", label: "Kâr faktörü", help: "Brüt kâr bölü brüt zarar. Birin üstü kârlı." },
  { value: "win_rate_pct", label: "Kazanma oranı %", help: "Kârlı işlemlerin oranı. Tek başına kâr hakkında bir şey söylemez." },
  { value: "max_drawdown_pct", label: "Maksimum düşüş %", help: "Zirveden dibe en kötü düşüş. Düşük olması iyidir." },
];

/** Colour scale for the heatmap: red below the neutral point, green above. */
function heatColour(value: number | null, metric: string): string {
  if (value === null || !Number.isFinite(value)) {
    return "transparent";
  }
  const neutral = metric === "profit_factor" ? 1 : 0;
  const scale = metric === "return_pct" ? 40 : metric === "win_rate_pct" ? 20 : metric === "sharpe_ratio" ? 1.5 : 0.25;
  const normalised = Math.max(-1, Math.min(1, (value - neutral) / scale));
  const alpha = Math.abs(normalised) * 0.65 + 0.05;
  return normalised >= 0
    ? `rgba(34, 197, 94, ${alpha.toFixed(3)})`
    : `rgba(239, 68, 68, ${alpha.toFixed(3)})`;
}

function statusTone(status: string): "success" | "warning" | "danger" | "neutral" {
  if (status === "COMPLETED") return "success";
  if (status === "RUNNING") return "warning";
  if (status === "FAILED") return "danger";
  return "neutral";
}

/** Step 1: choose the grid and see what it costs before committing to it. */
function SweepBuilder({ onStarted }: { onStarted: (sweep: SweepView) => void }) {
  const { pushToast } = useAppState();
  const options = useOnceQuery(["sweep-options"], sweepService.options);

  const [strategies, setStrategies] = useState<string[]>([]);
  const [timeframes, setTimeframes] = useState<string[]>(DEFAULT_TIMEFRAMES);
  const [symbolSource, setSymbolSource] = useState("top_volume");
  const [topN, setTopN] = useState(50);
  const [months, setMonths] = useState(12);
  const [leverage, setLeverage] = useState(2);
  const [takerFee, setTakerFee] = useState(0.04);
  const [slippage, setSlippage] = useState(0.02);
  const [estimate, setEstimate] = useState<SweepEstimate | null>(null);

  const allStrategies = options.data?.strategies ?? [];
  const end = toIsoDate(new Date());
  const start = daysAgoIso(Math.round(months * 30.44));

  const payload: SweepPayload = useMemo(
    () => ({
      name: "",
      strategy_keys: strategies,
      symbols: [],
      timeframes,
      start: start + "T00:00:00Z",
      end: end + "T00:00:00Z",
      starting_capital: 10_000,
      leverage,
      taker_fee_pct: takerFee,
      slippage_pct: slippage,
      funding_rate_pct_per_8h: 0.01,
      apply_funding: true,
      respect_daily_limits: true,
      download_missing: true,
      min_candles: 600,
      symbol_source: symbolSource,
      top_n: topN,
      min_quote_volume: 0,
    }),
    [strategies, timeframes, start, end, leverage, takerFee, slippage, symbolSource, topN],
  );

  const estimateMutation = useApiMutation(() => sweepService.estimate(payload), [], {
    onSuccess: (result) => setEstimate(result),
    onError: (error) => pushToast(error.message, "error"),
  });

  const startMutation = useApiMutation(() => sweepService.start(payload), [["sweeps"]], {
    onSuccess: (result) => {
      pushToast(result.message, "success");
      onStarted(result.sweep);
    },
    onError: (error) => pushToast(error.message, "error"),
  });

  const toggleIn = (list: string[], value: string, setter: (next: string[]) => void) => {
    setter(list.includes(value) ? list.filter((item) => item !== value) : [...list, value]);
  };

  return (
    <Panel
      title="1. Izgarayı kur"
      subtitle="Seçilen her strateji, seçilen her markette ve her zaman diliminde çalıştırılır."
    >
      {options.isLoading && <Loading label="Loading options" />}

      <div className="field">
        <label>
          Strategies{" "}
          <span className="muted">
            ({strategies.length === 0 ? "all " + allStrategies.length : strategies.length} seçili)
          </span>
        </label>
        <div className="btn-row wrap">
          <button type="button" className="btn btn-sm" onClick={() => setStrategies([])}>
            Use all
          </button>
          {allStrategies.map((key) => (
            <button
              key={key}
              type="button"
              className={"btn btn-sm " + (strategies.includes(key) ? "btn-primary" : "btn-ghost")}
              onClick={() => toggleIn(strategies, key, setStrategies)}
            >
              {key}
            </button>
          ))}
        </div>
      </div>

      <div className="field">
        <label>Timeframes ({timeframes.length} seçili)</label>
        <div className="btn-row wrap">
          {ALL_TIMEFRAMES.map((timeframe) => (
            <button
              key={timeframe}
              type="button"
              className={"btn btn-sm " + (timeframes.includes(timeframe) ? "btn-primary" : "btn-ghost")}
              onClick={() => toggleIn(timeframes, timeframe, setTimeframes)}
            >
              {timeframe}
            </button>
          ))}
          <button type="button" className="btn btn-sm" onClick={() => setTimeframes(ALL_TIMEFRAMES)}>
            14'ü de
          </button>
          <button type="button" className="btn btn-sm" onClick={() => setTimeframes(DEFAULT_TIMEFRAMES)}>
            Reset
          </button>
        </div>
        {timeframes.some((tf) => ["1m", "3m", "5m"].includes(tf)) && (
          <p className="muted small">
            1m, 3m and 5m multiply both the runtime and the download by a large factor,
            and they are where the transaction costs have beaten the edge in every study
            run on this platform so far.
          </p>
        )}
      </div>

      <div className="grid grid-4">
        <div className="field">
          <label htmlFor="symbol-source">Marketler</label>
          <select
            id="symbol-source"
            value={symbolSource}
            onChange={(event) => setSymbolSource(event.target.value)}
          >
            {SYMBOL_SOURCES.map((source) => (
              <option key={source.value} value={source.value}>
                {source.label}
              </option>
            ))}
          </select>
          <span className="muted small">
            {SYMBOL_SOURCES.find((item) => item.value === symbolSource)?.hint}
          </span>
        </div>
        {symbolSource === "top_volume" && (
          <div className="field">
            <label htmlFor="top-n">Kaç tane</label>
            <input
              id="top-n"
              type="number"
              min={1}
              max={600}
              value={topN}
              onChange={(event) => setTopN(Number(event.target.value))}
            />
          </div>
        )}
        <div className="field">
          <label htmlFor="months">Geçmiş (ay)</label>
          <input
            id="months"
            type="number"
            min={1}
            max={48}
            value={months}
            onChange={(event) => setMonths(Number(event.target.value))}
          />
        </div>
        <div className="field">
          <label htmlFor="leverage">Kaldıraç</label>
          <input
            id="leverage"
            type="number"
            min={1}
            max={20}
            value={leverage}
            onChange={(event) => setLeverage(Number(event.target.value))}
          />
        </div>
        <div className="field">
          <label htmlFor="taker-fee">Komisyon %</label>
          <input
            id="taker-fee"
            type="number"
            step={0.01}
            value={takerFee}
            onChange={(event) => setTakerFee(Number(event.target.value))}
          />
        </div>
        <div className="field">
          <label htmlFor="slippage">Kayma %</label>
          <input
            id="slippage"
            type="number"
            step={0.01}
            value={slippage}
            onChange={(event) => setSlippage(Number(event.target.value))}
          />
        </div>
      </div>

      <div className="btn-row">
        <button
          type="button"
          className="btn"
          onClick={() => estimateMutation.mutate(undefined as never)}
          disabled={estimateMutation.isPending || timeframes.length === 0}
        >
          {estimateMutation.isPending ? "Calculating..." : "Maliyeti hesapla"}
        </button>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => startMutation.mutate(undefined as never)}
          disabled={startMutation.isPending || timeframes.length === 0}
        >
          {startMutation.isPending ? "Başlatılıyor…" : "Testi başlat"}
        </button>
      </div>

      {estimate && (
        <div className="stack">
          <div className="grid grid-4">
            <div className="mini-stat">
              <span>Test sayısı</span>
              <strong>{estimate.cells.toLocaleString()}</strong>
            </div>
            <div className="mini-stat">
              <span>Tahmini süre</span>
              <strong>
                {estimate.estimated_hours >= 1
                  ? estimate.estimated_hours.toFixed(1) + " h"
                  : estimate.estimated_minutes.toFixed(0) + " min"}
              </strong>
            </div>
            <div className="mini-stat">
              <span>Mum sayısı</span>
              <strong>{estimate.total_candles.toLocaleString()}</strong>
            </div>
            <div className="mini-stat">
              <span>Disk alanı</span>
              <strong>
                {estimate.estimated_storage_mb >= 1024
                  ? (estimate.estimated_storage_mb / 1024).toFixed(1) + " GB"
                  : estimate.estimated_storage_mb.toFixed(0) + " MB"}
              </strong>
            </div>
          </div>
          {estimate.warnings.map((warning) => (
            <Banner tone="warning" key={warning}>
              {warning}
            </Banner>
          ))}
          <p className="muted small">
            {estimate.symbol_count?.toLocaleString()} markets, {estimate.strategies}{" "}
            strategies, {estimate.timeframes} timeframes.{" "}
            {estimate.estimated_download_requests.toLocaleString()} candle downloads on the
            first run; later runs reuse the cache.
          </p>
        </div>
      )}
    </Panel>
  );
}

/** A live progress card for a sweep that is still running. */
function SweepProgress({ sweep }: { sweep: SweepView }) {
  const { pushToast } = useAppState();
  const cancel = useApiMutation(() => sweepService.cancel(sweep.id), [["sweeps"], ["sweep", sweep.id]], {
    onSuccess: (response) => pushToast(response.message, "info"),
  });

  // The backend stores naive UTC timestamps, so they have to be parsed as UTC:
  // letting the browser read them as local time turns a 90 minute job into a
  // "3 days remaining" estimate.
  const startedAt = parseUtc(sweep.started_at);
  const remaining =
    sweep.finished_runs > 0 && startedAt
      ? ((Date.now() - startedAt.getTime()) / 1000 / sweep.finished_runs) *
        (sweep.total_runs - sweep.finished_runs)
      : null;

  return (
    <Panel
      title={sweep.name}
      subtitle={sweep.current_task ? "Running: " + sweep.current_task : sweep.status}
      actions={
        <div className="btn-row">
          <Badge tone={statusTone(sweep.status)}>{sweep.status}</Badge>
          {sweep.is_running && (
            <button
              type="button"
              className="btn btn-sm btn-danger"
              onClick={() => cancel.mutate(undefined as never)}
              disabled={cancel.isPending || sweep.cancel_requested}
            >
              {sweep.cancel_requested ? "Durduruluyor…" : "Durdur"}
            </button>
          )}
        </div>
      }
    >
      <ProgressBar
        value={sweep.progress_pct}
        tone={sweep.status === "FAILED" ? "negative" : "accent"}
        leftLabel={`${sweep.finished_runs.toLocaleString()} / ${sweep.total_runs.toLocaleString()} backtests`}
        rightLabel={`${sweep.progress_pct}%`}
      />
      <div className="grid grid-4">
        <div className="mini-stat">
          <span>Tamamlanan</span>
          <strong>{sweep.completed_runs.toLocaleString()}</strong>
        </div>
        <div className="mini-stat">
          <span>Atlanan (veri yok)</span>
          <strong>{sweep.skipped_runs.toLocaleString()}</strong>
        </div>
        <div className="mini-stat">
          <span>Başarısız</span>
          <strong>{sweep.failed_runs.toLocaleString()}</strong>
        </div>
        <div className="mini-stat">
          <span>{sweep.is_running ? "Time remaining" : "Duration"}</span>
          <strong>
            {sweep.is_running
              ? remaining
                ? formatDuration(remaining)
                : "estimating"
              : formatDuration(sweep.duration_seconds)}
          </strong>
        </div>
      </div>
      {sweep.error_message && <Banner tone="danger">{sweep.error_message}</Banner>}
    </Panel>
  );
}

/** The heatmap: one metric averaged over a two dimensional pivot. */
function SweepMatrixView({ sweepId }: { sweepId: number }) {
  const [rowsAxis, setRowsAxis] = useState("strategy_key");
  const [columnsAxis, setColumnsAxis] = useState("timeframe");
  const [metric, setMetric] = useState("expectancy_r");
  const [minTrades, setMinTrades] = useState(20);

  const matrix = usePolledQuery(
    ["sweep-matrix", sweepId, rowsAxis, columnsAxis, metric, minTrades],
    () => sweepService.matrix(sweepId, rowsAxis, columnsAxis, metric, minTrades),
    REFRESH_SLOW,
  );

  const data = matrix.data;
  const selectedMetric = METRICS.find((item) => item.value === metric);

  return (
    <Panel
      title="3. Edge nerede hayatta kalıyor?"
      subtitle={selectedMetric?.help}
      actions={
        <div className="filter-bar compact">
          <select value={metric} onChange={(event) => setMetric(event.target.value)}>
            {METRICS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
          <select value={rowsAxis} onChange={(event) => setRowsAxis(event.target.value)}>
            <option value="strategy_key">Rows: strategy</option>
            <option value="symbol">Rows: market</option>
            <option value="timeframe">Rows: timeframe</option>
          </select>
          <select value={columnsAxis} onChange={(event) => setColumnsAxis(event.target.value)}>
            <option value="timeframe">Columns: timeframe</option>
            <option value="symbol">Columns: market</option>
            <option value="strategy_key">Columns: strategy</option>
          </select>
          <input
            type="number"
            min={0}
            value={minTrades}
            title="Ignore cells with fewer trades than this"
            onChange={(event) => setMinTrades(Number(event.target.value))}
          />
        </div>
      }
    >
      {matrix.isLoading && <Loading label="Aggregating" />}
      {matrix.error && <ErrorState error={matrix.error} />}
      {data && data.rows.length === 0 && (
        <Banner tone="info">
          No cell has at least {minTrades} trades yet. Either the sweep has just started,
          or the filter is stricter than the results.
        </Banner>
      )}
      {data && data.rows.length > 0 && (
        <div className="table-wrap">
          <table className="heatmap">
            <thead>
              <tr>
                <th />
                {data.columns.map((column) => (
                  <th key={column} className="numeric">
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row) => (
                <tr key={row}>
                  <th scope="row">{row}</th>
                  {data.columns.map((column) => {
                    const cell: SweepMatrixCell | undefined = data.cells[row]?.[column];
                    return (
                      <td
                        key={column}
                        className="numeric heat-cell"
                        style={{ background: heatColour(cell?.value ?? null, metric) }}
                        title={
                          cell
                            ? `${cell.cells} backtests, ${cell.trades.toLocaleString()} trades`
                            : "no data"
                        }
                      >
                        {cell?.value === null || cell?.value === undefined
                          ? "-"
                          : formatNumber(cell.value, metric === "expectancy_r" ? 3 : 2)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted small">
        {minTrades} işlemden az olan hücreler dışlanır: birkaç işlem her sayıyı gösterebilir
        ve hiçbir şey ifade etmez.
      </p>
    </Panel>
  );
}

/** The verdict panel: what the grid says once all the cells are in. */
function SweepVerdict({ sweep }: { sweep: SweepView }) {
  const summary = sweep.summary;
  if (!summary || summary.cells_with_enough_trades === 0) {
    return null;
  }

  const positive = summary.average_expectancy_r > 0;
  const tone = positive ? "success" : "warning";
  return (
    <Panel title="2. Izgara ne diyor">
      <div className="grid grid-4">
        <div className="mini-stat">
          <span>Sayılan test</span>
          <strong>{summary.cells_with_enough_trades.toLocaleString()}</strong>
        </div>
        <div className="mini-stat">
          <span>Kârlı</span>
          <strong className={pnlClass(summary.profitable_pct - 50)}>
            {summary.profitable_pct}%
          </strong>
        </div>
        <div className="mini-stat">
          <span>Al-tut'u geçen</span>
          <strong>{summary.beat_buy_and_hold_pct}%</strong>
        </div>
        <div className="mini-stat">
          <span>Ortalama beklenti</span>
          <strong className={pnlClass(summary.average_expectancy_r)}>
            {formatNumber(summary.average_expectancy_r, 4)} R
          </strong>
        </div>
      </div>

      <Banner tone={tone}>
        {positive ? (
          <>
            The average cell earns {formatNumber(summary.average_expectancy_r, 4)}R per trade
            after costs. That is a positive average, not a guarantee: it has to hold on data
            the parameters never saw before it means anything. Run a walk-forward on the best
            cells before trusting it, and keep live trading off until then.
          </>
        ) : (
          <>
            The average cell loses {formatNumber(Math.abs(summary.average_expectancy_r), 4)}R
            per trade after costs, and only {summary.profitable_pct}% of them finish in
            profit. That is the transaction cost drag, not a bad choice of coin: the fee,
            the spread and the slippage are paid on every trade in every direction.
          </>
        )}
      </Banner>

      <p className="muted small">
        Counted over cells with at least {summary.min_trades_for_inclusion} trades.
        "Beat buy and hold" compares each cell against simply holding that coin over the
        same window.
      </p>
    </Panel>
  );
}

/** Filterable, sortable table of every cell in the grid. */
function SweepResults({ sweepId }: { sweepId: number }) {
  const [strategy, setStrategy] = useState("");
  const [timeframe, setTimeframe] = useState("");
  const [symbol, setSymbol] = useState("");
  const [minTrades, setMinTrades] = useState(20);
  const [sort, setSort] = useState("expectancy_r");
  const [page, setPage] = useState(0);
  const pageSize = 50;

  const results = usePolledQuery(
    ["sweep-results", sweepId, strategy, timeframe, symbol, minTrades, sort, page],
    () =>
      sweepService.results(sweepId, {
        strategy: strategy || undefined,
        timeframe: timeframe || undefined,
        symbol: symbol || undefined,
        min_trades: minTrades,
        sort,
        descending: sort !== "max_drawdown_pct",
        limit: pageSize,
        offset: page * pageSize,
      }),
    REFRESH_SLOW,
  );

  const data = results.data;
  const pageCount = data ? Math.ceil(data.total / pageSize) : 0;

  return (
    <Panel
      title="4. Tüm sonuçlar"
      subtitle={data ? data.total.toLocaleString() + " cells match the filters" : ""}
    >
      <div className="filter-bar">
        <input
          type="search"
          placeholder="Market, e.g. BTC/USDT"
          value={symbol}
          onChange={(event) => {
            setSymbol(event.target.value.toUpperCase());
            setPage(0);
          }}
        />
        <input
          type="search"
          placeholder="Strategy key"
          value={strategy}
          onChange={(event) => {
            setStrategy(event.target.value);
            setPage(0);
          }}
        />
        <select
          value={timeframe}
          onChange={(event) => {
            setTimeframe(event.target.value);
            setPage(0);
          }}
        >
          <option value="">Any timeframe</option>
          {ALL_TIMEFRAMES.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
        <select value={sort} onChange={(event) => setSort(event.target.value)}>
          {METRICS.map((item) => (
            <option key={item.value} value={item.value}>
              Sort: {item.label}
            </option>
          ))}
        </select>
        <input
          type="number"
          min={0}
          value={minTrades}
          title="Minimum trades"
          onChange={(event) => {
            setMinTrades(Number(event.target.value));
            setPage(0);
          }}
        />
      </div>

      {results.isLoading && <Loading label="Loading results" />}
      {results.error && <ErrorState error={results.error} />}

      {data && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Strateji</th>
                <th>Market</th>
                <th>TF</th>
                <th className="numeric">İşlem</th>
                <th className="numeric">Return %</th>
                <th className="numeric">Buy &amp; hold %</th>
                <th className="numeric">Excess %</th>
                <th className="numeric">Expectancy R</th>
                <th className="numeric">Profit factor</th>
                <th className="numeric">Sharpe</th>
                <th className="numeric">Kazanma %</th>
                <th className="numeric">Max DD %</th>
                <th className="numeric">Komisyon</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row) => (
                <tr key={row.id}>
                  <td>{row.strategy_key}</td>
                  <td>{row.symbol}</td>
                  <td>{row.timeframe}</td>
                  <td className="numeric">{row.total_trades.toLocaleString()}</td>
                  <td className={"numeric " + pnlClass(row.return_pct)}>
                    {formatNumber(row.return_pct, 1)}
                  </td>
                  <td className={"numeric " + pnlClass(row.buy_hold_return_pct)}>
                    {formatNumber(row.buy_hold_return_pct, 1)}
                  </td>
                  <td className={"numeric " + pnlClass(row.excess_return_pct)}>
                    {formatNumber(row.excess_return_pct, 1)}
                  </td>
                  <td className={"numeric " + pnlClass(row.expectancy_r)}>
                    {formatNumber(row.expectancy_r, 4)}
                  </td>
                  <td className={"numeric " + pnlClass(row.profit_factor - 1)}>
                    {formatNumber(row.profit_factor, 2)}
                  </td>
                  <td className={"numeric " + pnlClass(row.sharpe_ratio)}>
                    {formatNumber(row.sharpe_ratio, 2)}
                  </td>
                  <td className="numeric">{formatNumber(row.win_rate_pct, 1)}</td>
                  <td className="numeric">{formatNumber(row.max_drawdown_pct, 1)}</td>
                  <td className="numeric">${formatNumber(row.total_fees, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {pageCount > 1 && (
        <div className="pager">
          <button
            type="button"
            className="btn btn-sm"
            disabled={page === 0}
            onClick={() => setPage((value) => Math.max(0, value - 1))}
          >
            Previous
          </button>
          <span>
            Page {page + 1} of {pageCount}
          </span>
          <button
            type="button"
            className="btn btn-sm"
            disabled={page + 1 >= pageCount}
            onClick={() => setPage((value) => value + 1)}
          >
            Next
          </button>
        </div>
      )}
    </Panel>
  );
}

export function SweepLabPage() {
  const [activeId, setActiveId] = useState<number | null>(null);
  const sweeps = usePolledQuery(["sweeps"], () => sweepService.list(20), REFRESH_FAST);

  const list = sweeps.data ?? [];
  const running = list.filter((item) => item.is_running || item.status === "RUNNING");
  const selectedId = activeId ?? running[0]?.id ?? list[0]?.id ?? null;

  const detail = usePolledQuery(
    ["sweep", selectedId],
    () => sweepService.detail(selectedId as number),
    REFRESH_FAST,
    { enabled: selectedId !== null },
  );

  const sweep = detail.data;

  return (
    <div className="stack">
      <Panel title="Toplu test">
        <Banner tone="info">
          Toplu test, seçtiğiniz her stratejiyi seçtiğiniz her markette ve her zaman diliminde
          çalıştırır ve her kombinasyon için tek satır sonuç saklar. Binlerce çalıştırma
          için tam ayrıntı (varlık eğrisi, işlem listesi) tutulmaz, ama her hücre yeniden
          üretilebilir: ilginç bulduğunuzu Tek test sekmesinde tekrar çalıştırın.
        </Banner>
      </Panel>

      <SweepBuilder onStarted={(created) => setActiveId(created.id)} />

      {list.length > 0 && (
        <Panel title="Testler" subtitle="Sonuçlarını görmek için birini seçin">
          <div className="btn-row wrap">
            {list.map((item) => (
              <button
                key={item.id}
                type="button"
                className={"btn btn-sm " + (item.id === selectedId ? "btn-primary" : "btn-ghost")}
                onClick={() => setActiveId(item.id)}
              >
                #{item.id} {item.status === "RUNNING" ? `${item.progress_pct}%` : item.status}{" "}
                <span className="muted">({item.total_runs.toLocaleString()} cells)</span>
              </button>
            ))}
          </div>
        </Panel>
      )}

      {detail.error && <ErrorState error={detail.error} />}
      {sweep && (
        <>
          <SweepProgress sweep={sweep} />
          <SweepVerdict sweep={sweep} />
          <SweepMatrixView sweepId={sweep.id} />
          <SweepResults sweepId={sweep.id} />
        </>
      )}
    </div>
  );
}
