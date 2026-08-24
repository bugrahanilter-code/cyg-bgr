import { useState } from "react";

import { Banner } from "@/components/StateViews";
import { Modal } from "@/components/Modal";
import { useApiMutation } from "@/hooks/useApi";
import { systemService } from "@/services/tradingService";
import { useAppState } from "@/state/appStateContext";
import type { EmergencyStopLevel } from "@/types/api";

const LEVELS: Array<{
  level: EmergencyStopLevel;
  title: string;
  description: string;
  className: string;
}> = [
  {
    level: "HALT_NEW_ENTRIES",
    title: "1. Yeni işlem açmayı durdur",
    description:
      "Açık pozisyonlar stop ve hedefleriyle kalır. Yeni pozisyon açılmaz.",
    className: "btn btn-warning btn-block",
  },
  {
    level: "CLOSE_ALL_POSITIONS",
    title: "2. Tüm açık pozisyonları kapat",
    description:
      "Her açık pozisyon için piyasa emri gönderir, sonra yeni girişleri engeller.",
    className: "btn btn-danger btn-block",
  },
  {
    level: "FULL_STOP",
    title: "3. Sistemi tamamen durdur",
    description:
      "Motoru tamamen durdurur. Siz kaldırana kadar yeniden başlatmadan sonra da durur.",
    className: "btn btn-danger btn-block",
  },
];

interface Props {
  currentLevel: EmergencyStopLevel;
}

/** The three-level kill switch. Always reachable from the top bar. */
export function EmergencyStopPanel({ currentLevel }: Props) {
  const { pushToast } = useAppState();
  const [pending, setPending] = useState<EmergencyStopLevel | null>(null);

  const mutation = useApiMutation(
    (level: EmergencyStopLevel) =>
      systemService.emergencyStop(level, "Panelden tetiklendi"),
    [["system-status"], ["overview"], ["positions"], ["health"]],
    {
      onSuccess: (response) => pushToast(response.message, "success"),
      onError: (error) => pushToast(error.message, "error"),
    },
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {currentLevel !== "NONE" && (
        <Banner tone="danger">
          Acil durdurma etkin: <strong>{currentLevel}</strong>. Siz kaldırana kadar yeni
          pozisyon açılmayacak.
        </Banner>
      )}

      {LEVELS.map((item) => (
        <div key={item.level} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <button
            type="button"
            className={item.className}
            disabled={mutation.isPending}
            onClick={() => setPending(item.level)}
          >
            {item.title}
          </button>
          <small className="muted">{item.description}</small>
        </div>
      ))}

      {currentLevel !== "NONE" && (
        <button
          type="button"
          className="btn btn-success btn-block"
          disabled={mutation.isPending}
          onClick={() => setPending("NONE")}
        >
          Acil durdurmayı kaldır
        </button>
      )}

      <Modal
        open={pending !== null}
        title="Onay"
        onClose={() => setPending(null)}
        footer={
          <>
            <button
              type="button"
              className="btn btn-danger"
              onClick={() => {
                if (pending) {
                  mutation.mutate(pending);
                }
                setPending(null);
              }}
            >
              Evet, uygula
            </button>
            <button type="button" className="btn" onClick={() => setPending(null)}>
              Vazgeç
            </button>
          </>
        }
      >
        <p>
          Acil durdurmayı <strong>{pending}</strong> seviyesine almak üzeresiniz.
        </p>
        {pending === "CLOSE_ALL_POSITIONS" && (
          <Banner tone="warning">
            Her açık pozisyon güncel piyasa fiyatından kapatılır. Zararlar
            kalıcı hale gelir.
          </Banner>
        )}
      </Modal>
    </div>
  );
}
