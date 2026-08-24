import { Badge, sideTone } from "@/components/Badge";
import { DataTable } from "@/components/DataTable";
import type { Column } from "@/components/DataTable";
import { Panel } from "@/components/Panel";
import { ProgressBar } from "@/components/ProgressBar";
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

const positionColumns: Array<Column<PositionView>> = [
  { key: "symbol", header: "Symbol", render: (row) => <strong>{row.symbol}</strong> },
  {
    key: "side",
    header: "Side",
    render: (row) => <Badge tone={sideTone(row.side)}>{row.side}</Badge>,
  },
  { key: "strategy", header: "Strategy", render: (row) => row.strategy },
  { key: "qty", header: "Size", numeric: true, render: (row) => formatQuantity(row.quantity) },
  { key: "entry", header: "Entry", numeric: true, render: (row) => formatPrice(row.entry_price) },
  {
    key: "current",
    header: "Price",
    numeric: true,
    render: (row) => formatPrice(row.current_price),
  },
  {
    key: "pnl",
    header: "Unrealised",
    numeric: true,
    render: (row) => (
      <span className={pnlClass(row.unrealized_pnl)}>
        {formatSignedCurrency(row.unrealized_pnl)}
      </span>
    ),
  },
];

export function OverviewPage() {
  const { data, isLoading, error } = usePolledQuery(
    ["overview"],
    dashboardService.overview,
    REFRESH_FAST,
  );

  if (isLoading && !data) {
    return <Loading label="Loading the dashboard..." />;
  }
  if (error) {
    return <ErrorState error={error} hint="Is the backend running on port 8000?" />;
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
      <div className="page-header">
        <div>
          <h1>Overview</h1>
          <p>
            Live snapshot of the trading engine. All numbers come from the backend; the
            dashboard performs no trading logic of its own.
          </p>
        </div>
        <div className="row">
          <Badge tone={bot.mode === "live" ? "danger" : "info"}>{bot.mode.toUpperCase()}</Badge>
          <Badge tone={bot.status === "RUNNING" ? "success" : "neutral"}>{bot.status}</Badge>
        </div>
      </div>

      {risk.daily_target_reached && (
        <Banner tone="success">
          Daily profit target reached. New entries are paused; open positions are still
          managed. The bot will not increase risk to earn more today.
        </Banner>
      )}
      {risk.daily_loss_limit_reached && (
        <Banner tone="danger">
          Daily loss limit reached. The system is in safe mode and will not open new trades
          today.
        </Banner>
      )}
      {risk.blocked_reasons.length > 0 && !risk.daily_target_reached && (
        <Banner tone="warning">
          New entries are currently blocked: {risk.blocked_reasons.join(", ")}
        </Banner>
      )}

      <div className="grid grid-4">
        <StatCard label="Equity" value={formatCurrency(account.equity)} hint={"Balance " + formatCurrency(account.balance)} />
        <StatCard label="Available" value={formatCurrency(account.available_balance)} hint={"Margin in use " + formatCurrency(account.used_margin)} />
        <StatCard
          label="Unrealised PnL"
          value={formatSignedCurrency(account.unrealized_pnl)}
          tone={pnlClass(account.unrealized_pnl) as "positive" | "negative" | "neutral"}
          hint={risk.open_positions + " open position(s)"}
        />
        <StatCard
          label="Today"
          value={formatSignedCurrency(pnl.realized_today)}
          tone={pnlClass(pnl.realized_today) as "positive" | "negative" | "neutral"}
          hint={formatPercent(pnl.daily_return_pct)}
        />
        <StatCard
          label="This week"
          value={formatSignedCurrency(pnl.weekly)}
          tone={pnlClass(pnl.weekly) as "positive" | "negative" | "neutral"}
        />
        <StatCard
          label="This month"
          value={formatSignedCurrency(pnl.monthly)}
          tone={pnlClass(pnl.monthly) as "positive" | "negative" | "neutral"}
        />
        <StatCard
          label="Drawdown"
          value={formatPercent(-risk.current_drawdown_pct)}
          tone={risk.current_drawdown_pct > risk.max_drawdown_pct / 2 ? "warning" : "neutral"}
          hint={"Limit " + risk.max_drawdown_pct + "%"}
        />
        <StatCard
          label="Trades today"
          value={risk.trades_today + " / " + risk.max_trades_per_day}
          hint={risk.consecutive_losses + " consecutive losses"}
        />
      </div>

      <div className="grid grid-2">
        <Panel title="Daily profit target" subtitle={"Target " + risk.daily_profit_target_pct + "%"}>
          <ProgressBar
            value={targetProgress}
            tone={risk.daily_target_reached ? "positive" : "accent"}
            leftLabel={formatPercent(pnl.daily_return_pct) + " today"}
            rightLabel={targetProgress.toFixed(0) + "% of the target"}
          />
          <div className="definition">
            <span>Status</span>
            <span>{risk.daily_target_reached ? "Target reached" : "In progress"}</span>
          </div>
        </Panel>

        <Panel title="Daily loss limit" subtitle={"Limit " + risk.daily_loss_limit_pct + "%"}>
          <ProgressBar
            value={Math.min(100, lossUsage)}
            tone={lossUsage > 70 ? "negative" : "warning"}
            leftLabel={formatPercent(pnl.daily_return_pct)}
            rightLabel={Math.min(100, lossUsage).toFixed(0) + "% of the limit used"}
          />
          <div className="definition">
            <span>Fees today</span>
            <span>{formatCurrency(pnl.fees_today)}</span>
          </div>
          <div className="definition">
            <span>Funding today</span>
            <span>{formatCurrency(pnl.funding_today)}</span>
          </div>
        </Panel>
      </div>

      <Panel title="Equity curve" subtitle="Sampled by the trading engine while it runs">
        {data.equity_curve.length > 1 ? (
          <LineAreaChart
            data={data.equity_curve.map((point) => ({ time: point.time, value: point.equity }))}
            height={260}
          />
        ) : (
          <div className="table-empty">
            The equity curve appears once the engine has been running for a few minutes.
          </div>
        )}
      </Panel>

      <div className="grid grid-2">
        <Panel title="Open positions">
          <DataTable
            columns={positionColumns}
            rows={data.positions}
            rowKey={(row) => row.id}
            emptyMessage="No open positions."
          />
        </Panel>

        <Panel title="Prices">
          <ul className="list-reset">
            {data.symbols.map((symbol) => (
              <li key={symbol} className="definition">
                <span>{symbol}</span>
                <span>{formatPrice(data.prices[symbol] ?? null)}</span>
              </li>
            ))}
          </ul>
          <div className="disclaimer">
            Prices come from the Binance public feed. When they become stale the Risk Engine
            refuses to open new positions.
          </div>
        </Panel>
      </div>

      <Panel title="Recent trades">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Closed</th>
                <th>Symbol</th>
                <th>Side</th>
                <th>Strategy</th>
                <th className="numeric">Entry</th>
                <th className="numeric">Exit</th>
                <th className="numeric">Net PnL</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {data.recent_trades.length === 0 && (
                <tr>
                  <td colSpan={8} className="table-empty">
                    No trades yet.
                  </td>
                </tr>
              )}
              {data.recent_trades.map((trade) => {
                const row = trade as Record<string, string | number | boolean>;
                const net = Number(row.net_pnl ?? 0);
                return (
                  <tr key={String(row.uid)}>
                    <td>{formatDateTime(String(row.closed_at))}</td>
                    <td>{String(row.symbol)}</td>
                    <td>
                      <Badge tone={sideTone(String(row.side))}>{String(row.side)}</Badge>
                    </td>
                    <td>{String(row.strategy)}</td>
                    <td className="numeric">{formatPrice(Number(row.entry_price))}</td>
                    <td className="numeric">{formatPrice(Number(row.exit_price))}</td>
                    <td className={"numeric " + pnlClass(net)}>{formatSignedCurrency(net)}</td>
                    <td>{String(row.exit_reason)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>

      <div className="disclaimer">
        Past performance, including backtest and paper trading results, is not a prediction of
        future returns. This platform gives no profit guarantee.
      </div>
    </>
  );
}
