import { Navigate, Route, Routes } from "react-router-dom";

import { Layout } from "@/components/Layout";
import { ActivityPage } from "@/pages/Activity";
import { MarketsPage } from "@/pages/Markets";
import { OverviewPage } from "@/pages/Overview";
import { RiskSettingsPage } from "@/pages/RiskSettings";
import { RotationPage } from "@/pages/Rotation";
import { SettingsPage } from "@/pages/Settings";
import { StrategyHubPage } from "@/pages/StrategyHub";
import { SystemMonitorPage } from "@/pages/SystemMonitor";
import { TestHubPage } from "@/pages/TestHub";

/**
 * Nine destinations. Pages that show one subject at two scales (open positions
 * and history, one backtest and the whole grid) share a route and split with a
 * tab, so the sidebar stays scannable.
 */
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<OverviewPage />} />
        <Route path="markets" element={<MarketsPage />} />
        <Route path="trades" element={<ActivityPage />} />
        <Route path="strategies" element={<StrategyHubPage />} />
        <Route path="backtest" element={<TestHubPage />} />
        <Route path="rotation" element={<RotationPage />} />
        <Route path="risk" element={<RiskSettingsPage />} />
        <Route path="system" element={<SystemMonitorPage />} />
        <Route path="settings" element={<SettingsPage />} />

        {/* Old bookmarks keep working. */}
        <Route path="positions" element={<Navigate to="/trades" replace />} />
        <Route path="comparison" element={<Navigate to="/strategies" replace />} />
        <Route path="sweep" element={<Navigate to="/backtest" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
