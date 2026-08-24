import { Badge } from "@/components/Badge";
import { ClosePositionButton } from "@/components/ClosePositionButton";
import { DataTable } from "@/components/DataTable";
import type { Column } from "@/components/DataTable";
import { Panel } from "@/components/Panel";
import { ProgressBar } from "@/components/ProgressBar";
import { ResetAccountButton } from "@/components/ResetAccountButton";
import { StatCard } from "@/components/StatCard";
import { Banner, ErrorState, Loading } from "@/components/StateViews";
import { LineAreaChart } from "@/charts/LineAreaChart";
import { REFRESH_FAST, usePolledQuery } from "@/hooks/useApi";
import { dashboardService } from "@/services/tradingService";
import type { PositionView } from "@/types/api";
import {
  formatCurrency,
  formatDateTime,
  formatPercent,
  formatPrice,
  formatQuantity,
  formatSignedCurrency,
  pnlClass,
} from "@/utils/format";
import { sideTone } from "@/utils/tone";

const EXIT_REASONS: Record<string, string> = {
  stop_loss: "Stop",
  take_profit: "Hedef",
  trailing_stop: "Takip eden stop",
  signal_reversal: "Ters sinyal",
  signal_exit: "Çıkış sinyali",
  manual: "Manuel",
  emergency_stop: "Acil durdurma",
  daily_limit: "Günlük limit",
  liquidation: "Likidasyon",
  end_of_backtest: "Test sonu",
};

const positionColumns: Array<Column<PositionView>> = [
  { key: "symbol", header: "Market", render: (row) => <strong>{row.symbol}</strong> },
  {
    key: "side",
    header: "Yön",
    render: (row) => (
      <Badge tone={sideTone(row.side)}>{row.side === "LONG" ? "AL" : "SAT"}</Badge>
    ),
  },
  { key: "strategy", header: "Strateji", render: (row) => row.strategy },
  { key: "qty", header: "Miktar", numeric: true, render: (row) => formatQuantity(row.quantity) },
  { key: "entry", header: "Giriş", numeric: true, render: (row) => formatPrice(row.entry_price) },
  {
    key: "current",
    header: "Fiyat",
    numeric: true,
    render: (row) => formatPrice(row.current_price),
  },
  {
    key: "value",
    header: "Değer",
    numeric: true,
    render: (row) => formatCurrency(row.current_notional),
  },
  {
    key: "pnl",
    header: "Net K/Z",
    numeric: true,
    render: (row) => (
      <span
        className={pnlClass(row.unrealized_pnl)}
        title={
          "Brüt " +
          formatSignedCurrency(row.unrealized_pnl_gross) +
          ", maliyetler " +
          formatCurrency(row.total_costs)
        }
      >
        {formatSignedCurrency(row.unrealized_pnl)}
      </span>
    ),
  },
  {
    key: "pricePct",
    header: "Fiyat %",
    numeric: true,
    render: (row) => (
      <span className={pnlClass(row.price_change_pct)} title="Piyasanın hareketi. Kaldıraçtan bağımsız.">
        {row.price_change_pct > 0 ? "+" : ""}
        {row.price_change_pct.toFixed(2)}%
      </span>
    ),
  },
  {
    key: "marginPct",
    header: "Teminat %",
    numeric: true,
    render: (row) => (
      <span
        className={pnlClass(row.return_on_margin_pct)}
        title={"Teminata etkisi, " + row.leverage.toFixed(0) + "x kaldıraçla çarpılmış."}
      >
        {row.return_on_margin_pct > 0 ? "+" : ""}
        {row.return_on_margin_pct.toFixed(1)}%
      </span>
    ),
  },
  {
    key: "close",
    header: "",
    render: (row) => <ClosePositionButton position={row} />,
  },
];

export function OverviewPage() {
  const { data, isLoading, error } = usePolledQuery(
    ["overview"],
    dashboardService.overview,
    REFRESH_FAST,
  );

  if (isLoading && !data) {
    return <Loading label="Panel yükleniyor…" />;
  }
  if (error) {
    return <ErrorState error={error} hint="Arka uç 8000 portunda çalışıyor mu?" />;
  }
  if (!data) {
    return null;
  }

  const { account, pnl, risk, bot } = data;
  const targetProgress = Math.max(0, Math.min(100, risk.daily_target_progress_pct));
  const lossUsage =
    risk.daily_loss_limit_pct > 0
      ? Math.max(0, (-pnl.daily_return_pct / risk.daily_loss_limit_pct) * 100)
      : 0;

  return (
    <>
      <div className="page-header row-between">
        <div>
          <h1>Genel Bakış</h1>
          <p>
            {bot.mode === "live"
              ? "Gerçek para modunda çalışıyor."
              : "Kağıt para modunda çalışıyor: emirler simüle edilir, borsaya gitmez."}{" "}
            Tüm rakamlar arka uçtan gelir.
          </p>
        </div>
        <div className="row">
          <Badge tone={bot.mode === "live" ? "danger" : "info"}>
            {bot.mode === "live" ? "GERÇEK" : "KAĞIT"}
          </Badge>
          <Badge tone={bot.status === "RUNNING" ? "success" : "neutral"}>
            {bot.status === "RUNNING" ? "Çalışıyor" : "Durdu"}
          </Badge>
        </div>
      </div>

      {risk.daily_target_reached && (
        <Banner tone="success">
          <strong>Günlük kâr hedefine ulaşıldı.</strong> Yeni giriş yapılmıyor, açık
          pozisyonlar yönetilmeye devam ediyor. Bot bugün daha fazla kazanmak için risk
          artırmaz.
        </Banner>
      )}
      {risk.daily_loss_limit_reached && (
        <Banner tone="danger">
          <strong>Günlük zarar limitine ulaşıldı.</strong> Sistem güvenli moda geçti, bugün
          yeni işlem açmayacak.
        </Banner>
      )}
      {risk.blocked_reasons.length > 0 && !risk.daily_target_reached && (
        <Banner tone="warning">
          Yeni giriş şu anda engelli: {risk.blocked_reasons.join(", ")}
        </Banner>
      )}

      {/* Four numbers that answer "how am I doing". Everything else is detail
          and sits below, so the eye has somewhere to land first. */}
      <div className="grid grid-4">
        <StatCard
          label="Toplam varlık"
          value={formatCurrency(account.equity)}
          hint={"Bakiye " + formatCurrency(account.balance)}
        />
        <StatCard
          label="Bugün"
          value={formatSignedCurrency(pnl.realized_today)}
          tone={pnlClass(pnl.realized_today) as "positive" | "negative" | "neutral"}
          hint={formatPercent(pnl.daily_return_pct)}
        />
        <StatCard
          label="Anlık kâr/zarar"
          value={formatSignedCurrency(account.unrealized_pnl)}
          tone={pnlClass(account.unrealized_pnl) as "positive" | "negative" | "neutral"}
          hint={risk.open_positions + " açık pozisyon"}
        />
        <StatCard
          label="Zirveden düşüş"
          value={formatPercent(-risk.current_drawdown_pct)}
          tone={risk.current_drawdown_pct > risk.max_drawdown_pct / 2 ? "warning" : "neutral"}
          hint={"Limit %" + risk.max_drawdown_pct}
        />
      </div>

      <Panel title="Ayrıntı">
        <div className="grid grid-4">
          <div className="mini-stat">
            <span>Kullanılabilir</span>
            <strong>{formatCurrency(account.available_balance)}</strong>
          </div>
          <div className="mini-stat">
            <span>Kullanılan teminat</span>
            <strong>{formatCurrency(account.used_margin)}</strong>
          </div>
          <div className="mini-stat">
            <span>Bu hafta</span>
            <strong className={pnlClass(pnl.weekly)}>
              {formatSignedCurrency(pnl.weekly)}
            </strong>
          </div>
          <div className="mini-stat">
            <span>Bu ay</span>
            <strong className={pnlClass(pnl.monthly)}>
              {formatSignedCurrency(pnl.monthly)}
            </strong>
          </div>
          <div className="mini-stat">
            <span>Bugünkü işlem</span>
            <strong>
              {risk.trades_today} / {risk.max_trades_per_day}
            </strong>
          </div>
          <div className="mini-stat">
            <span>Üst üste zarar</span>
            <strong>{risk.consecutive_losses}</strong>
          </div>
          <div className="mini-stat">
            <span>Bugünkü komisyon</span>
            <strong>{formatCurrency(pnl.fees_today)}</strong>
          </div>
          <div className="mini-stat">
            <span>Bugünkü funding</span>
            <strong>{formatCurrency(pnl.funding_today)}</strong>
          </div>
        </div>
      </Panel>

      <div className="grid grid-2">
        <Panel title="Günlük kâr hedefi" subtitle={"Hedef %" + risk.daily_profit_target_pct}>
          <ProgressBar
            value={targetProgress}
            tone={risk.daily_target_reached ? "positive" : "accent"}
            leftLabel={formatPercent(pnl.daily_return_pct) + " bugün"}
            rightLabel={"hedefin %" + targetProgress.toFixed(0) + "'i"}
          />
        </Panel>

        <Panel title="Günlük zarar limiti" subtitle={"Limit %" + risk.daily_loss_limit_pct}>
          <ProgressBar
            value={Math.min(100, lossUsage)}
            tone={lossUsage > 70 ? "negative" : "warning"}
            leftLabel={formatPercent(pnl.daily_return_pct)}
            rightLabel={"limitin %" + Math.min(100, lossUsage).toFixed(0) + "'i kullanıldı"}
          />
        </Panel>
      </div>

      <Panel
        title="Varlık eğrisi"
        subtitle="Motor çalışırken düzenli olarak örneklenir"
        actions={bot.mode !== "live" ? <ResetAccountButton /> : undefined}
      >
        {data.equity_curve.length > 1 ? (
          <LineAreaChart
            data={data.equity_curve.map((point) => ({ time: point.time, value: point.equity }))}
            height={260}
          />
        ) : (
          <div className="empty-state">
            <strong>Henüz eğri yok</strong>
            Motor birkaç dakika çalıştıktan sonra burada görünecek.
          </div>
        )}
      </Panel>

      <div className="grid grid-2">
        <Panel title="Açık pozisyonlar">
          <DataTable
            columns={positionColumns}
            rows={data.positions}
            rowKey={(row) => row.id}
            emptyMessage="Açık pozisyon yok."
          />
        </Panel>

        <Panel title="Fiyatlar">
          <ul className="list-reset">
            {data.symbols.map((symbol) => (
              <li key={symbol} className="definition">
                <span>{symbol}</span>
                <span>{formatPrice(data.prices[symbol] ?? null)}</span>
              </li>
            ))}
          </ul>
          <div className="disclaimer" style={{ marginTop: 12 }}>
            Fiyatlar Binance genel yayınından gelir. Veri bayatladığında Risk Motoru yeni
            pozisyon açmayı reddeder.
          </div>
        </Panel>
      </div>

      <Panel title="Son işlemler">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Kapanış</th>
                <th>Market</th>
                <th>Yön</th>
                <th>Strateji</th>
                <th className="numeric">Giriş</th>
                <th className="numeric">Çıkış</th>
                <th className="numeric">Net K/Z</th>
                <th>Sebep</th>
              </tr>
            </thead>
            <tbody>
              {data.recent_trades.length === 0 && (
                <tr>
                  <td colSpan={8} className="empty-state">
                    <strong>Henüz işlem yok</strong>
                    Motor çalışıyorsa, bir strateji sinyal ürettiğinde ilk işlem burada
                    görünecek.
                  </td>
                </tr>
              )}
              {data.recent_trades.map((trade) => {
                const row = trade as Record<string, string | number | boolean>;
                const net = Number(row.net_pnl ?? 0);
                const reason = String(row.exit_reason);
                return (
                  <tr key={String(row.uid)}>
                    <td>{formatDateTime(String(row.closed_at))}</td>
                    <td>{String(row.symbol)}</td>
                    <td>
                      <Badge tone={sideTone(String(row.side))}>
                        {String(row.side) === "LONG" ? "AL" : "SAT"}
                      </Badge>
                    </td>
                    <td>{String(row.strategy)}</td>
                    <td className="numeric">{formatPrice(Number(row.entry_price))}</td>
                    <td className="numeric">{formatPrice(Number(row.exit_price))}</td>
                    <td className={"numeric " + pnlClass(net)}>{formatSignedCurrency(net)}</td>
                    <td className="muted">{EXIT_REASONS[reason] ?? reason}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>

      <div className="disclaimer">
        Geçmiş performans — backtest ve kağıt işlem sonuçları dahil — gelecekteki getirinin
        göstergesi değildir. Bu platform kâr garantisi vermez.
      </div>
    </>
  );
}
