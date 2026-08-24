import { useState } from "react";

import { Modal } from "@/components/Modal";
import { Banner } from "@/components/StateViews";
import { useApiMutation } from "@/hooks/useApi";
import { positionService } from "@/services/tradingService";
import { useAppState } from "@/state/appStateContext";
import type { PositionView } from "@/types/api";
import { formatCurrency, formatPrice, formatSignedCurrency, pnlClass } from "@/utils/format";

const PRESETS = [25, 50, 75, 100];

/**
 * Closes a position, in whole or in part.
 *
 * Partial closing is a reduce-only market order for a share of the quantity;
 * the rest of the position keeps its entry price, stop and target, so a later
 * exit is booked against the same levels it was opened on.
 */
export function ClosePositionButton({ position }: { position: PositionView }) {
  const { pushToast } = useAppState();
  const [open, setOpen] = useState(false);
  const [percent, setPercent] = useState(100);

  const close = useApiMutation(
    () => positionService.close(position.id, "manual", percent),
    [["positions"], ["overview"], ["trades"], ["comparison"]],
    {
      onSuccess: (response) => {
        pushToast(response.message, response.ok === false ? "error" : "success");
        setOpen(false);
        setPercent(100);
      },
      onError: (error) => pushToast(error.message, "error"),
    },
  );

  const share = percent / 100;
  const closingValue = position.current_notional * share;
  const estimatedPnl = position.unrealized_pnl * share;

  return (
    <>
      <button
        type="button"
        className="btn btn-sm"
        onClick={(event) => {
          event.stopPropagation();
          setOpen(true);
        }}
      >
        Kapat
      </button>

      <Modal
        open={open}
        title={position.symbol + " pozisyonunu kapat"}
        onClose={() => setOpen(false)}
      >
        <div className="stack">
          <div className="grid grid-4">
            <div className="mini-stat">
              <span>Yön</span>
              <strong>{position.side === "LONG" ? "AL" : "SAT"}</strong>
            </div>
            <div className="mini-stat">
              <span>Giriş</span>
              <strong>{formatPrice(position.entry_price)}</strong>
            </div>
            <div className="mini-stat">
              <span>Şimdi</span>
              <strong>{formatPrice(position.current_price)}</strong>
            </div>
            <div className="mini-stat">
              <span>Net K/Z</span>
              <strong className={pnlClass(position.unrealized_pnl)}>
                {formatSignedCurrency(position.unrealized_pnl)}
              </strong>
            </div>
          </div>

          <p className="small muted">
            Brüt {formatSignedCurrency(position.unrealized_pnl_gross)} eksi{" "}
            {formatCurrency(position.total_costs)} maliyet (giriş komisyonu{" "}
            {formatCurrency(position.entry_fees_paid)}, çıkış komisyonu{" "}
            {formatCurrency(position.estimated_exit_fee)}, funding{" "}
            {formatCurrency(position.funding_paid)}).
          </p>

          <div className="field">
            <label>Ne kadarı kapatılsın?</label>
            <div className="btn-row">
              {PRESETS.map((value) => (
                <button
                  key={value}
                  type="button"
                  className={"btn btn-sm " + (percent === value ? "btn-primary" : "")}
                  onClick={() => setPercent(value)}
                >
                  %{value}
                </button>
              ))}
            </div>
            <input
              type="range"
              min={1}
              max={100}
              step={1}
              value={percent}
              onChange={(event) => setPercent(Number(event.target.value))}
            />
            <small>
              Pozisyonun %{percent}&apos;i piyasa emriyle kapatılır:{" "}
              <strong>{formatCurrency(closingValue)}</strong> değerinde, tahmini{" "}
              <span className={pnlClass(estimatedPnl)}>
                {formatSignedCurrency(estimatedPnl)}
              </span>{" "}
              kâr/zarar ile.
            </small>
          </div>

          {percent < 100 && (
            <Banner tone="info">
              Kalan %{100 - percent} açık kalır ve aynı giriş fiyatı, stop ve hedefiyle
              yönetilmeye devam eder. Giriş maliyetleri iki parça arasında oransal olarak
              bölünür.
            </Banner>
          )}

          <div className="btn-row">
            <button
              type="button"
              className="btn btn-danger"
              disabled={close.isPending}
              onClick={() => close.mutate(undefined as never)}
            >
              {close.isPending ? "Kapatılıyor…" : "Piyasa fiyatından kapat"}
            </button>
            <button type="button" className="btn" onClick={() => setOpen(false)}>
              Vazgeç
            </button>
          </div>

          <p className="small muted">
            Piyasa emri kullanılır, yani gerçekleşme fiyatı gösterilenden biraz farklı
            olabilir.
          </p>
        </div>
      </Modal>
    </>
  );
}
