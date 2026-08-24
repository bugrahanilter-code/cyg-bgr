import { Badge } from "@/components/Badge";
import { ClosePositionButton } from "@/components/ClosePositionButton";
import { Panel } from "@/components/Panel";
import { ErrorState, Loading } from "@/components/StateViews";
import { REFRESH_FAST, useApiMutation, usePolledQuery } from "@/hooks/useApi";
import { positionService } from "@/services/tradingService";
import { useAppState } from "@/state/appStateContext";
import {
  formatCurrency,
  formatDateTime,
  formatPrice,
  formatQuantity,
  formatSignedCurrency,
  pnlClass,
} from "@/utils/format";
import { sideTone } from "@/utils/tone";

export function PositionsPage() {
  const { pushToast } = useAppState();
  const { data, isLoading, error } = usePolledQuery(
    ["positions"],
    () => positionService.list(),
    REFRESH_FAST,
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
      <Panel
        title={"Açık pozisyonlar (" + positions.length + ")"}
        actions={
          positions.length > 0 ? (
            <button
              type="button"
              className="btn btn-sm btn-danger"
              disabled={closeAll.isPending}
              onClick={() => closeAll.mutate(undefined)}
            >
              {closeAll.isPending ? "Kapatılıyor…" : "Hepsini kapat"}
            </button>
          ) : undefined
        }
      >
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Market</th>
                <th>Yön</th>
                <th>Strateji</th>
                <th className="numeric">Miktar</th>
                <th className="numeric">Değer</th>
                <th className="numeric">Giriş</th>
                <th className="numeric">Fiyat</th>
                <th className="numeric">Stop</th>
                <th className="numeric">Hedef</th>
                <th className="numeric">Kaldıraç</th>
                <th className="numeric">Teminat</th>
                <th className="numeric">Likidasyon</th>
                <th
                  className="numeric"
                  title="Giriş komisyonu, funding ve kapatırken ödenecek çıkış komisyonu düşülmüş hâli."
                >
                  Net K/Z
                </th>
                <th className="numeric" title="Piyasanın ne kadar hareket ettiği. Kaldıraçtan bağımsız.">
                  Fiyat %
                </th>
                <th
                  className="numeric"
                  title="Bu hareketin yatırdığınız teminata etkisi. Kaldıraç bu oranı çarpar."
                >
                  Teminat %
                </th>
                <th>Açılış</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {positions.length === 0 && (
                <tr>
                  <td colSpan={14} className="table-empty">
                    Açık pozisyon yok.
                  </td>
                </tr>
              )}
              {positions.map((position) => (
                <tr key={position.id}>
                  <td>
                    <strong>{position.symbol}</strong>
                  </td>
                  <td>
                    <Badge tone={sideTone(position.side)}>
                      {position.side === "LONG" ? "AL" : "SAT"}
                    </Badge>
                  </td>
                  <td>{position.strategy}</td>
                  <td className="numeric">{formatQuantity(position.quantity)}</td>
                  <td className="numeric">{formatCurrency(position.current_notional)}</td>
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
                    <div className="small muted" title="Brüt kâr/zarar, maliyetler hariç">
                      brüt {formatSignedCurrency(position.unrealized_pnl_gross)}
                    </div>
                  </td>
                  <td className={"numeric " + pnlClass(position.price_change_pct)}>
                    {position.price_change_pct > 0 ? "+" : ""}
                    {position.price_change_pct.toFixed(2)}%
                  </td>
                  <td className={"numeric " + pnlClass(position.return_on_margin_pct)}>
                    {position.return_on_margin_pct > 0 ? "+" : ""}
                    {position.return_on_margin_pct.toFixed(1)}%
                    <div className="small muted">{position.leverage.toFixed(0)}x</div>
                  </td>
                  <td>{formatDateTime(position.opened_at)}</td>
                  <td>
                    <ClosePositionButton position={position} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {positions.length > 0 && (
        <Panel title="Bu pozisyon neden açıldı?">
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
