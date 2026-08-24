import { useState } from "react";

import { Banner } from "@/components/StateViews";
import { Modal } from "@/components/Modal";
import { useApiMutation } from "@/hooks/useApi";
import { systemService } from "@/services/tradingService";
import { useAppState } from "@/state/AppState";
import type { EmergencyStopLevel } from "@/types/api";

const LEVELS: Array<{
  level: EmergencyStopLevel;
  title: string;
  description: string;
  className: string;
}> = [
  {
    level: "HALT_NEW_ENTRIES",
    title: "1. Stop opening new trades",
    description:
      "Existing positions keep their stop loss and take profit. Nothing new is opened.",
    className: "btn btn-warning btn-block",
  },
  {
    level: "CLOSE_ALL_POSITIONS",
    title: "2. Close every open position",
    description:
      "Sends a market order for every open position and then blocks new entries.",
    className: "btn btn-danger btn-block",
  },
  {
    level: "FULL_STOP",
    title: "3. Stop the whole system",
    description:
      "Stops the trading engine completely. It stays stopped after a restart until you clear it.",
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
      systemService.emergencyStop(level, "Triggered from the dashboard"),
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
          Emergency stop is active: <strong>{currentLevel}</strong>. No new position will be
          opened until you clear it.
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
          Clear the emergency stop
        </button>
      )}

      <Modal
        open={pending !== null}
        title="Confirm"
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
              Yes, do it
            </button>
            <button type="button" className="btn" onClick={() => setPending(null)}>
              Cancel
            </button>
          </>
        }
      >
        <p>
          You are about to set the emergency stop to <strong>{pending}</strong>.
        </p>
        {pending === "CLOSE_ALL_POSITIONS" && (
          <Banner tone="warning">
            Every open position will be closed at the current market price. Losses become
            permanent.
          </Banner>
        )}
      </Modal>
    </div>
  );
}
