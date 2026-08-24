import { useState } from "react";

import { Modal } from "@/components/Modal";
import { Banner } from "@/components/StateViews";
import { useApiMutation } from "@/hooks/useApi";
import { tradingService } from "@/services/tradingService";
import { useAppState } from "@/state/appStateContext";

interface ResetAccountButtonProps {
  /** Balance the account returns to. */
  startingBalance?: number;
  label?: string;
  className?: string;
}

/**
 * Resets the paper account: balance, equity curve, daily counters and,
 * optionally, the trade history.
 *
 * The equity curve and the daily statistics live in their own tables, separate
 * from the trades. Clearing only the trades used to leave a chart still
 * climbing away from an account that had just been set back to its starting
 * balance, which is why they are cleared together here.
 *
 * Destructive, so it asks first and names exactly what it will delete. It is
 * not styled as a red alarm button: it is a normal action that happens to need
 * confirmation.
 */
export function ResetAccountButton({
  startingBalance = 10_000,
  label = "Sıfırla",
  className = "btn btn-sm btn-ghost",
}: ResetAccountButtonProps) {
  const { pushToast } = useAppState();
  const [open, setOpen] = useState(false);
  const [balance, setBalance] = useState(startingBalance);
  const [clearHistory, setClearHistory] = useState(true);
  const [clearCurve, setClearCurve] = useState(true);

  const reset = useApiMutation(
    () =>
      tradingService.resetPaper({
        starting_balance: balance,
        clear_history: clearHistory,
        clear_equity_curve: clearCurve,
      }),
    [["overview"], ["positions"], ["trades"], ["comparison"], ["settings"], ["system-status"]],
    {
      onSuccess: (response) => {
        pushToast(response.message, "success");
        setOpen(false);
      },
      onError: (error) => pushToast(error.message, "error"),
    },
  );

  return (
    <>
      <button type="button" className={className} onClick={() => setOpen(true)}>
        {label}
      </button>

      <Modal open={open} title="Kağıt hesabı sıfırla" onClose={() => setOpen(false)}>
        <div className="stack">
          <p className="muted">
            Bakiye başlangıç değerine döner. Aşağıda seçtikleriniz kalıcı olarak silinir.
            Gerçek para hesabınıza ve borsadaki hiçbir şeye dokunulmaz.
          </p>

          <div className="field">
            <label htmlFor="reset-balance">Başlangıç bakiyesi (USDT)</label>
            <input
              id="reset-balance"
              type="number"
              min={1}
              step={100}
              value={balance}
              onChange={(event) => setBalance(Number(event.target.value))}
            />
          </div>

          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={clearCurve}
              onChange={(event) => setClearCurve(event.target.checked)}
            />
            Equity eğrisini ve günlük istatistikleri temizle
          </label>

          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={clearHistory}
              onChange={(event) => setClearHistory(event.target.checked)}
            />
            İşlem geçmişini, emirleri ve sinyalleri sil
          </label>

          {!clearCurve && clearHistory && (
            <Banner tone="warning">
              Equity eğrisini temizlemezseniz grafik, silinmiş işlemlerin bıraktığı
              yükselişi göstermeye devam eder ve bakiyeyle uyuşmaz.
            </Banner>
          )}

          <Banner tone="danger">Bu işlem geri alınamaz.</Banner>

          <div className="btn-row">
            <button
              type="button"
              className="btn btn-danger"
              disabled={reset.isPending}
              onClick={() => reset.mutate(undefined as never)}
            >
              {reset.isPending ? "Sıfırlanıyor…" : "Evet, sıfırla"}
            </button>
            <button type="button" className="btn" onClick={() => setOpen(false)}>
              Vazgeç
            </button>
          </div>

          <p className="small muted">
            Açık pozisyon varsa sıfırlama reddedilir. Önce pozisyonları kapatın.
          </p>
        </div>
      </Modal>
    </>
  );
}
