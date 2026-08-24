import { useState } from "react";

import { Segmented } from "@/components/Segmented";
import { PositionsPage } from "@/pages/Positions";
import { TradesPage } from "@/pages/Trades";

type Tab = "open" | "history";

/**
 * Open positions and the trade journal are the same subject at two points in
 * its life, so they share one destination instead of two sidebar entries.
 */
export function ActivityPage() {
  const [tab, setTab] = useState<Tab>("open");

  return (
    <>
      <div className="page-header">
        <h1>İşlemler</h1>
        <p>
          Açık pozisyonlar ve tamamlanmış işlem geçmişi. Kağıt, gerçek ve backtest
          işlemleri aynı defterde tutulur.
        </p>
      </div>

      <Segmented
        value={tab}
        onChange={setTab}
        options={[
          { value: "open", label: "Açık pozisyonlar" },
          { value: "history", label: "Geçmiş" },
        ]}
      />

      {tab === "open" ? <PositionsPage /> : <TradesPage />}
    </>
  );
}
