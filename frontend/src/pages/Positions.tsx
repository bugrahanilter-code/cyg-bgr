import { Badge, sideTone } from "@/components/Badge";
import { Panel } from "@/components/Panel";
import { ErrorState, Loading } from "@/components/StateViews";
import { REFRESH_FAST, useApiMutation, usePolledQuery } from "@/hooks/useApi";
import { positionService } from "@/services/tradingService";
import { useAppState } from "@/state/AppState";
import {
  formatCurrency,
  formatDateTime,
  formatPrice,
  formatQuantity,
  formatSignedCurrency,
  pnlClass,
} from "@/utils/format";

export function PositionsPage() {
  const { pushToast } = useAppState();
  const { data, isLoading, error } = usePolledQuery(
    ["positions"],
    () => positionService.list(),
    REFRESH_FAST,
  );

  const closeOne = useApiMutation(
    (id: number) => positionService.close(id),
    [["positions"], ["overview"], ["trades"]],
    {
      onSuccess: (response) => pushToast(response.message, "success"),
      onError: (mutationError) => pushToast(mutationError.message, "error"),
    },
  );

  const closeAll = useApiMutation(
    () => positionService.closeAll(),
    [["positions"], ["overview"], ["trades"]],
    {
      onSuccess: (response) => pushToast(response.message, "success"),
      onError: (mutationError) => pushToast(mutationError.message, "error"),
    },
  );

  if (isLoading && !data) {
    return <Loading />;
  }
  if (error) {
    return <ErrorState error={error} />;
  }

  const positions = data ?? [];

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Positions</h1>
          <p>Everything the platform currently holds, including margin and liquidation data.</p>
        </div>
        <button
          type="button"
          className="btn btn-danger"
          disabled={positions.length === 0 || closeAll.isPending}
          onClick={() => closeAll.mutate(undefined)}
        >
          Close every position
        </button>
      </div>

      <Panel title={"Open positions (" + positions.length + ")"}>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Side</th>
                <th>Strategy</th>
                <th className="numeric">Size</th>
                <th className="numeric">Entry</th>
                <th className="numeric">Price</th>
                <th className="numeric">Stop</th>
                <th className="numeric">Target</th>
                <th className="numeric">Leverage</th>
                <th className="numeric">Margin</th>
                <th className="numeric">Liquidation</th>
                <th className="numeric">Unrealised</th>
                <th>Opened</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {positions.length === 0 && (
                <tr>
                  <td colSpan={14} className="table-empty">
                    No open positions.
                  </td>
                </tr>
              )}
              {positions.map((position) => (
                <tr key={position.id}>
                  <td>
                    <strong>{position.symbol}</strong>
                  </td>
                  <td>
                    <Badge tone={sideTone(position.side)}>{position.side}</Badge>
                  </td>
                  <td>{position.strategy}</td>
                  <td className="numeric">{formatQuantity(position.quantity)}</td>
                  <td className="numeric">{formatPrice(position.entry_price)}</td>
                  <td className="numeric">{formatPrice(position.current_price)}</td>
                  <td className="numeric">
                    {formatPrice(position.trailing_stop ?? position.stop_loss)}
                  </td>
                  <td className="numeric">{formatPrice(position.take_profit)}</td>
                  <td className="numeric">{position.leverage.toFixed(1)}x</td>
                  <td className="numeric">{formatCurrency(position.margin)}</td>
                  <td className="numeric">{formatPrice(position.liquidation_price)}</td>
                  <td className={"numeric " + pnlClass(position.unrealized_pnl)}>
                    {formatSignedCurrency(position.unrealized_pnl)}
                    <div className="small muted">
                      {position.unrealized_pnl_pct.toFixed(2)}%
                    </div>
                  </td>
                  <td>{formatDateTime(position.opened_at)}</td>
                  <td>
                    <button
                      type="button"
                      className="btn btn-sm btn-danger"
                      disabled={closeOne.isPending}
                      onClick={() => closeOne.mutate(position.id)}
                    >
                      Close
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {positions.length > 0 && (
        <Panel title="Why was this position opened?">
          <ul className="list-reset">
            {positions.map((position) => (
              <li key={position.uid} className="definition">
                <span>
                  {position.symbol} ({position.market_regime}, confidence{" "}
                  {(position.signal_confidence * 100).toFixed(0)}%)
                </span>
                <span style={{ maxWidth: "60%", textAlign: "right", whiteSpace: "normal" }}>
                  {position.entry_reason || "-"}
                </span>
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </>
  );
}
