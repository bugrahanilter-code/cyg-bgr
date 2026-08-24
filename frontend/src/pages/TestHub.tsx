import { useState } from "react";

import { Segmented } from "@/components/Segmented";
import { BacktestLabPage } from "@/pages/BacktestLab";
import { SweepLabPage } from "@/pages/SweepLab";

type Tab = "single" | "matrix";

/**
 * One test in depth, or the whole grid at once. Same activity, two scales,
 * so one destination with a tab rather than two entries that look unrelated.
 */
export function TestHubPage() {
  const [tab, setTab] = useState<Tab>("single");

  return (
    <>
      <div className="page-header">
        <h1>Test</h1>
        <p>
          Bir stratejiyi geçmiş veride dene. Tek test derinlemesine tek bir sonucu,
          toplu test yüzlerce kombinasyonu birden gösterir.
        </p>
      </div>

      <Segmented
        value={tab}
        onChange={setTab}
        options={[
          { value: "single", label: "Tek test" },
          { value: "matrix", label: "Toplu test" },
        ]}
      />

      {tab === "single" ? <BacktestLabPage /> : <SweepLabPage />}
    </>
  );
}
