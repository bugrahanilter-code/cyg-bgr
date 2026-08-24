import { useState } from "react";

import { Segmented } from "@/components/Segmented";
import { ComparisonPage } from "@/pages/Comparison";
import { StrategiesPage } from "@/pages/Strategies";

type Tab = "list" | "compare";

/** The strategy list and the side-by-side comparison are one subject. */
export function StrategyHubPage() {
  const [tab, setTab] = useState<Tab>("list");

  return (
    <>
      <div className="page-header">
        <h1>Stratejiler</h1>
        <p>
          Stratejileri aç, kapat ve ayarla. Karşılaştırma sekmesi hepsini yan yana
          aynı ölçütlerle gösterir.
        </p>
      </div>

      <Segmented
        value={tab}
        onChange={setTab}
        options={[
          { value: "list", label: "Stratejiler" },
          { value: "compare", label: "Karşılaştırma" },
        ]}
      />

      {tab === "list" ? <StrategiesPage /> : <ComparisonPage />}
    </>
  );
}
