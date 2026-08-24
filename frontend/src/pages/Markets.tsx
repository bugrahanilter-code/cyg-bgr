import { useMemo, useState } from "react";

import { Badge } from "@/components/Badge";
import { Modal } from "@/components/Modal";
import { Panel } from "@/components/Panel";
import { Banner, ErrorState, Loading } from "@/components/StateViews";
import { TradingViewChart } from "@/components/TradingViewChart";
import { REFRESH_NORMAL, useApiMutation, usePolledQuery } from "@/hooks/useApi";
import { marketService } from "@/services/tradingService";
import { useAppState } from "@/state/appStateContext";
import type { MarketRow } from "@/types/api";
import { formatDateTime, formatNumber, formatPrice, pnlClass } from "@/utils/format";

const SORT_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "quote_volume_24h", label: "24s hacim" },
  { value: "change_24h_pct", label: "24s değişim" },
  { value: "last_price", label: "Fiyat" },
  { value: "spread_pct", label: "Spread" },
  { value: "atr_pct", label: "Oynaklık (ATR %)" },
  { value: "tv_rating", label: "TradingView notu" },
  { value: "range_position_pct", label: "24s bandındaki yer" },
  { value: "symbol", label: "İsim" },
];

const VOLUME_FILTERS: Array<{ value: number; label: string }> = [
  { value: 0, label: "Tüm hacimler" },
  { value: 10_000_000, label: "> $10M / 24h" },
  { value: 50_000_000, label: "> $50M / 24h" },
  { value: 200_000_000, label: "> $200M / 24h" },
  { value: 1_000_000_000, label: "> $1B / 24h" },
];

function compactUsd(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "-";
  }
  if (value >= 1e9) return "$" + (value / 1e9).toFixed(2) + "B";
  if (value >= 1e6) return "$" + (value / 1e6).toFixed(1) + "M";
  if (value >= 1e3) return "$" + (value / 1e3).toFixed(1) + "K";
  return "$" + value.toFixed(0);
}

function ratingTone(label: string): "success" | "danger" | "neutral" {
  if (label.includes("BUY")) return "success";
  if (label.includes("SELL")) return "danger";
  return "neutral";
}

/** Where the last price sits inside the 24 hour high/low band. */
function RangeBar({ row }: { row: MarketRow }) {
  const position = row.range_position_pct;
  if (position === null || position === undefined) {
    return <span className="muted">-</span>;
  }
  const clamped = Math.max(0, Math.min(100, position));
  return (
    <div className="range-bar" title={`Low ${formatPrice(row.low_24h)} / High ${formatPrice(row.high_24h)}`}>
      <div className="range-bar__track">
        <div className="range-bar__marker" style={{ left: clamped + "%" }} />
      </div>
      <span className="range-bar__value">{clamped.toFixed(0)}%</span>
    </div>
  );
}

/** Detail drawer: exchange filters, cached history and the TradingView chart. */
function MarketDetailModal({ symbol, onClose }: { symbol: string; onClose: () => void }) {
  const detail = usePolledQuery(["market-detail", symbol], () => marketService.detail(symbol), 15_000);
  const data = detail.data;

  return (
    <Modal open title={symbol} onClose={onClose} className="modal-wide">
      {detail.isLoading && <Loading label="Market ayrıntıları yükleniyor" />}
      {detail.error && <ErrorState error={detail.error} />}
      {data && (
        <div className="stack">
          <div className="grid grid-4">
            <div className="mini-stat">
              <span>Son</span>
              <strong>{formatPrice(data.market.last_price)}</strong>
            </div>
            <div className="mini-stat">
              <span>24s değişim</span>
              <strong className={pnlClass(data.market.change_24h_pct)}>
                {formatNumber(data.market.change_24h_pct, 2)}%
              </strong>
            </div>
            <div className="mini-stat">
              <span>24s hacim</span>
              <strong>{compactUsd(data.market.quote_volume_24h)}</strong>
            </div>
            <div className="mini-stat">
              <span>Spread</span>
              <strong>
                {data.market.spread_pct === null
                  ? "-"
                  : formatNumber(data.market.spread_pct, 4) + "%"}
              </strong>
            </div>
          </div>

          {data.reference && (
            <Banner tone={data.reference.tradable ? "info" : "warning"}>
              <strong>{data.reference.description}.</strong>{" "}
              {!data.reference.tradable && (
                <>
                  This market is <strong>research only</strong>: no exchange configured
                  here can fill an order on it, and the Risk Engine rejects any signal it
                  produces.{" "}
                </>
              )}
              Session: {data.reference.session} Candles come from{" "}
              {data.reference.history_source}.
              <br />
              {data.reference.notes}
            </Banner>
          )}

          {data.reference && !data.reference.has_volume && (
            <Banner tone="warning">
              <strong>This feed carries no volume data.</strong> Spot FX has no central
              exchange, so there is no consolidated volume to report and every bar shows
              zero.
              {data.reference.untestable_strategies.length > 0 && (
                <>
                  {" "}
                  <span className="mono">
                    {data.reference.untestable_strategies.join(", ")}
                  </span>{" "}
                  is gated on volume and can never produce a signal here. Its zero trades
                  mean <strong>could not run</strong>, not <strong>found nothing</strong>.
                </>
              )}
              {data.reference.degraded_strategies.length > 0 && (
                <>
                  {" "}
                  <span className="mono">
                    {data.reference.degraded_strategies.join(", ")}
                  </span>{" "}
                  read volume as one score component among several. They still trade here,
                  with that component permanently scoring zero.
                </>
              )}{" "}
              Every other strategy is unaffected.
            </Banner>
          )}

          {data.reference && Object.keys(data.reference.history_limits).length > 0 && (
            <p className="muted small">
              History available:{" "}
              {Object.entries(data.reference.history_limits)
                .map(([timeframe, limit]) => `${timeframe} ${limit}`)
                .join(", ")}
              .
            </p>
          )}

          <Banner tone="info">
            One round trip on this market costs roughly{" "}
            <strong>{formatNumber(data.market.round_trip_cost_pct, 3)}%</strong> (taker
            fee in and out, slippage in and out, plus the spread). A strategy has to earn
            more than that before it earns anything at all.
          </Banner>

          {data.market.tv_symbol ? (
            <TradingViewChart symbol={data.market.tv_symbol} interval="60" height={420} />
          ) : (
            <p className="muted small">
              No TradingView symbol is mapped for this market, so no chart is shown.
              The cached candles below are what a backtest actually runs on.
            </p>
          )}

          <div className="grid grid-2">
            <Panel title="Borsa kuralları">
              {data.filters ? (
                <dl className="definition-list">
                  <dt>Min notional</dt>
                  <dd>${formatNumber(Number(data.filters.min_notional), 2)}</dd>
                  <dt>Min quantity</dt>
                  <dd>{formatNumber(Number(data.filters.min_quantity), 6)}</dd>
                  <dt>Tick size</dt>
                  <dd>{formatNumber(Number(data.filters.tick_size), 8)}</dd>
                  <dt>Step size</dt>
                  <dd>{formatNumber(Number(data.filters.step_size), 8)}</dd>
                  <dt>Leverage cap</dt>
                  <dd>{String(data.filters.max_leverage)}x</dd>
                  <dt>Synced</dt>
                  <dd>{formatDateTime(String(data.filters.synced_at ?? ""))}</dd>
                </dl>
              ) : null}
              {data.filters ? (
                <p className="muted small">
                  Tick size, step size and the minimums come from Binance and are what
                  orders are rounded to. The leverage cap is a conservative platform
                  default: Binance only publishes the real brackets through an
                  authenticated endpoint. Either way the Risk Engine applies its own,
                  lower cap from Risk Settings.
                </p>
              ) : (
                <p className="muted">
                  This market is not in the local database yet. Use "Import every market".
                </p>
              )}
            </Panel>

            <Panel title="Yerel mum geçmişi">
              {Object.keys(data.data_coverage).length === 0 ? (
                <p className="muted">
                  Nothing downloaded yet. A backtest or a sweep downloads what it needs.
                </p>
              ) : (
                <dl className="definition-list">
                  {Object.entries(data.data_coverage).map(([timeframe, entry]) => (
                    <div key={timeframe} className="coverage-row">
                      <dt>{timeframe}</dt>
                      <dd>
                        {entry.candles.toLocaleString()} candles
                        <span className="muted">
                          {" "}
                          {formatDateTime(entry.from)} to {formatDateTime(entry.to)}
                        </span>
                      </dd>
                    </div>
                  ))}
                </dl>
              )}
            </Panel>
          </div>

          <Panel title="TradingView ek verileri">
            <div className="grid grid-4">
              <div className="mini-stat">
                <span>Rating</span>
                <strong>{data.market.tv_rating_label}</strong>
              </div>
              <div className="mini-stat">
                <span>RSI (1d)</span>
                <strong>{formatNumber(data.market.tv_rsi, 1)}</strong>
              </div>
              <div className="mini-stat">
                <span>ATR</span>
                <strong>{formatNumber(data.market.atr_pct, 2)}%</strong>
              </div>
              <div className="mini-stat">
                <span>Relative volume</span>
                <strong>{formatNumber(data.market.tv_relative_volume, 2)}x</strong>
              </div>
            </div>
            <p className="muted small">
              Context for a human only. No strategy, risk check or order in this
              platform reads these numbers.
            </p>
          </Panel>
        </div>
      )}
    </Modal>
  );
}

export function MarketsPage() {
  const { pushToast } = useAppState();
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("quote_volume_24h");
  const [descending, setDescending] = useState(true);
  const [minVolume, setMinVolume] = useState(0);
  const [onlyEnabled, setOnlyEnabled] = useState(false);
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const pageSize = 50;

  const universe = usePolledQuery(
    ["universe", search, sort, descending, minVolume, onlyEnabled, page],
    () =>
      marketService.universe({
        search,
        sort,
        descending,
        min_quote_volume: minVolume,
        only_enabled: onlyEnabled,
        limit: pageSize,
        offset: page * pageSize,
      }),
    REFRESH_NORMAL,
  );

  const syncAll = useApiMutation(
    () => marketService.syncAll({ min_quote_volume: 500_000 }),
    [["universe"], ["settings"], ["sweep-options"]],
    {
      onSuccess: (response) => pushToast(response.message, "success"),
      onError: (error) => pushToast(error.message, "error"),
    },
  );

  const toggle = useApiMutation(
    (payload: { symbols: string[]; enabled: boolean }) => marketService.setEnabled(payload),
    [["universe"], ["settings"], ["system-status"]],
    {
      onSuccess: (response) => pushToast(response.message, "success"),
      onError: (error) => pushToast(error.message, "error"),
    },
  );

  const data = universe.data;
  const rows = data?.rows ?? [];
  const pageCount = data ? Math.ceil(data.total / pageSize) : 0;
  const tvSource = data?.sources?.tradingview;

  const headline = useMemo(() => {
    if (!data) return "";
    return `${data.total.toLocaleString()} markets match. ${data.enabled_count} enabled for trading, ${data.known_count} stored locally.`;
  }, [data]);

  return (
    <div className="stack">
      <div className="page-header">
        <h1>Piyasalar</h1>
        <p>
          Binance'teki her market, canlı 24 saatlik verileriyle. Bir satıra tıklayarak
          borsa kurallarını, yerel mum geçmişini ve grafiği görebilirsiniz.
        </p>
      </div>

      <Panel
        title="Tüm marketler"
        subtitle={headline}
        actions={
          <div className="btn-row">
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => universe.refetch()}
              disabled={universe.isFetching}
            >
              {universe.isFetching ? "Yenileniyor…" : "Yenile"}
            </button>
            <button
              type="button"
              className="btn btn-sm btn-primary"
              onClick={() => syncAll.mutate(undefined as never)}
              disabled={syncAll.isPending}
            >
              {syncAll.isPending ? "Aktarılıyor…" : "Tüm marketleri aktar"}
            </button>
          </div>
        }
      >
        <Banner tone="info">
          Binance'teki her USDT perpetual marketi burada. Aktarmak onları{" "}
          <strong>backtest edilebilir</strong> yapar; hiçbirini işleme açmaz. Bir marketi
          işleme açmak ayrı bir tıklamadır: açık her market, her mumda bir strateji
          değerlendirmesi ve risk motorunun denetlemesi gereken bir pozisyon daha
          demektir.
        </Banner>

        {tvSource && !tvSource.ok && (
          <Banner tone="warning">
            TradingView verisine ulaşılamıyor ({tvSource.error ?? "bilinmeyen hata"}), bu
            yüzden not, RSI ve ATR sütunları boş. Fiyatlar ve 24 saatlik rakamlar
            Binance'ten gelir ve etkilenmez.
          </Banner>
        )}

        <div className="filter-bar">
          <input
            type="search"
            placeholder="BTC, PEPE, SOL ara…"
            value={search}
            onChange={(event) => {
              setSearch(event.target.value.toUpperCase());
              setPage(0);
            }}
          />
          <select
            value={sort}
            onChange={(event) => {
              setSort(event.target.value);
              setPage(0);
            }}
          >
            {SORT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                Sırala: {option.label}
              </option>
            ))}
          </select>
          <button type="button" className="btn btn-sm" onClick={() => setDescending((v) => !v)}>
            {descending ? "Yüksekten düşüğe" : "Düşükten yükseğe"}
          </button>
          <select
            value={minVolume}
            onChange={(event) => {
              setMinVolume(Number(event.target.value));
              setPage(0);
            }}
          >
            {VOLUME_FILTERS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={onlyEnabled}
              onChange={(event) => {
                setOnlyEnabled(event.target.checked);
                setPage(0);
              }}
            />
            Sadece açık olanlar
          </label>
        </div>

        {universe.isLoading && <Loading label="Borsa okunuyor" />}
        {universe.error && <ErrorState error={universe.error} />}

        {data && (
          <div className="table-wrap">
            <table className="market-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Market</th>
                  <th className="numeric">Fiyat</th>
                  <th className="numeric">24s %</th>
                  <th className="numeric">24s yüksek</th>
                  <th className="numeric">24s düşük</th>
                  <th>24s bant</th>
                  <th className="numeric">24s hacim</th>
                  <th className="numeric">Spread</th>
                  <th className="numeric">ATR %</th>
                  <th className="numeric">RSI</th>
                  <th>TV notu</th>
                  <th className="numeric">İşlem maliyeti</th>
                  <th>Durum</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={row.symbol}
                    className={row.enabled ? "row-enabled" : undefined}
                    onClick={() => setSelected(row.symbol)}
                  >
                    <td className="muted">{row.volume_rank}</td>
                    <td>
                      <strong>{row.base_asset}</strong>
                      <span className="muted"> /{row.quote_asset}</span>
                      {row.reference && (
                        <Badge tone={row.tradable ? "info" : "warning"}>
                          {row.tradable ? row.kind.toUpperCase() : "RESEARCH ONLY"}
                        </Badge>
                      )}
                    </td>
                    <td className="numeric">{formatPrice(row.last_price)}</td>
                    <td className={"numeric " + pnlClass(row.change_24h_pct)}>
                      {row.change_24h_pct > 0 ? "+" : ""}
                      {formatNumber(row.change_24h_pct, 2)}%
                    </td>
                    <td className="numeric">{formatPrice(row.high_24h)}</td>
                    <td className="numeric">{formatPrice(row.low_24h)}</td>
                    <td>
                      <RangeBar row={row} />
                    </td>
                    <td className="numeric">{compactUsd(row.quote_volume_24h)}</td>
                    <td className="numeric">
                      {row.spread_pct === null ? "-" : formatNumber(row.spread_pct, 4) + "%"}
                    </td>
                    <td className="numeric">{formatNumber(row.atr_pct, 2)}</td>
                    <td className="numeric">{formatNumber(row.tv_rsi, 0)}</td>
                    <td>
                      <Badge tone={ratingTone(row.tv_rating_label)}>
                        {row.tv_rating_label.replace("_", " ")}
                      </Badge>
                    </td>
                    <td className="numeric cost-cell" title="Giriş ve çıkış komisyonu, iki yönlü kayma ve canlı spread. Strateji her işlemde önce bunu aşmalı.">
                      {formatNumber(row.round_trip_cost_pct, 3)}%
                    </td>
                    <td>
                      {row.tradable ? (
                        <button
                          type="button"
                          className={"btn btn-sm " + (row.enabled ? "btn-danger" : "btn-primary")}
                          disabled={toggle.isPending}
                          onClick={(event) => {
                            event.stopPropagation();
                            toggle.mutate({ symbols: [row.symbol], enabled: !row.enabled });
                          }}
                        >
                          {row.enabled ? "Kapat" : "Aç"}
                        </button>
                      ) : (
                        <span className="muted small" title="Bu markette hiçbir borsa emir gerçekleştiremez">
                          sadece test
                        </span>
                      )}
                    </td>
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
              Önceki
            </button>
            <span>
              Sayfa {page + 1} / {pageCount}
            </span>
            <button
              type="button"
              className="btn btn-sm"
              disabled={page + 1 >= pageCount}
              onClick={() => setPage((value) => value + 1)}
            >
              Sonraki
            </button>
          </div>
        )}

        <p className="muted small">{data?.note}</p>
      </Panel>

      {selected && <MarketDetailModal symbol={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
