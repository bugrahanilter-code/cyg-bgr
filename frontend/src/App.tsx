import { Navigate, Route, Routes } from "react-router-dom";

import { Layout } from "@/components/Layout";
import { BacktestLabPage } from "@/pages/BacktestLab";
import { ComparisonPage } from "@/pages/Comparison";
import { OverviewPage } from "@/pages/Overview";
import { PositionsPage } from "@/pages/Positions";
import { RiskSettingsPage } from "@/pages/RiskSettings";
import { SettingsPage } from "@/pages/Settings";
import { StrategiesPage } from "@/pages/Strategies";
import { SystemMonitorPage } from "@/pages/SystemMonitor";
import { TradesPage } from "@/pages/Trades";

/** Route table. The dashboard is a pure client of the backend API. */
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<OverviewPage />} />
        <Route path="positions" element={<PositionsPage />} />
        <Route path="trades" element={<TradesPage />} />
        <Route path="strategies" element={<StrategiesPage />} />
        <Route path="comparison" element={<ComparisonPage />} />
        <Route path="backtest" element={<BacktestLabPage />} />
        <Route path="risk" element={<RiskSettingsPage />} />
        <Route path="system" element={<SystemMonitorPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
