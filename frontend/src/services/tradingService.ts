/** Service layer: every backend endpoint used by the dashboard. */

import type {
  BacktestDetail,
  BacktestSummary,
  BotStatus,
  Candle,
  ComparisonResponse,
  EmergencyStopLevel,
  HealthReport,
  LiveChecklist,
  MessageResponse,
  OverviewResponse,
  PositionView,
  RiskConfig,
  SettingsResponse,
  SignalRecord,
  StrategySummary,
  SyncTopSymbolsResponse,
  SystemEvent,
  TopSymbolResponse,
  TradeView,
  TradingConfig,
} from "@/types/api";

import { api } from "./apiClient";

// ---------------------------------------------------------------------------
// System
// ---------------------------------------------------------------------------
export const systemService = {
  status: () => api.get<BotStatus>("/system/status"),
  health: () => api.get<HealthReport>("/system/health"),
  events: (limit = 100, severity?: string) =>
    api.get<SystemEvent[]>("/system/events", { limit, severity }),
  startEngine: () => api.post<MessageResponse>("/system/engine/start"),
  stopEngine: () => api.post<MessageResponse>("/system/engine/stop"),
  emergencyStop: (level: EmergencyStopLevel, reason: string) =>
    api.post<MessageResponse>("/system/emergency-stop", { level, reason }),
};

// ---------------------------------------------------------------------------
// Dashboard, positions and trades
// ---------------------------------------------------------------------------
export const dashboardService = {
  overview: () => api.get<OverviewResponse>("/dashboard/overview"),
};

export const positionService = {
  list: (mode?: string) => api.get<PositionView[]>("/positions", { mode }),
  close: (id: number, reason = "manual") =>
    api.post<MessageResponse>("/positions/" + id + "/close", { reason }),
  closeAll: () => api.post<MessageResponse>("/positions/close-all"),
};

export interface TradeFilters {
  mode?: string;
  symbol?: string;
  strategy?: string;
  side?: string;
  result?: string;
  backtest_id?: number;
  limit?: number;
  offset?: number;
}

export const tradeService = {
  list: (filters: TradeFilters = {}) =>
    api.get<TradeView[]>("/trades", { ...filters }),
  signals: (limit = 50, mode?: string) =>
    api.get<SignalRecord[]>("/signals", { limit, mode }),
};

// ---------------------------------------------------------------------------
// Strategies
// ---------------------------------------------------------------------------
export const strategyService = {
  list: () => api.get<StrategySummary[]>("/strategies"),
  detail: (key: string) => api.get<StrategySummary>("/strategies/" + key),
  update: (key: string, payload: { enabled?: boolean; params?: Record<string, unknown> }) =>
    api.put<MessageResponse>("/strategies/" + key, payload),
  resetParams: (key: string) =>
    api.post<MessageResponse>("/strategies/" + key + "/reset-params"),
  comparison: (mode?: string) =>
    api.get<ComparisonResponse>("/strategies/comparison", { mode }),
};

// ---------------------------------------------------------------------------
// Backtesting
// ---------------------------------------------------------------------------
export interface BacktestRunPayload {
  strategy_key: string;
  symbol: string;
  timeframe: string;
  start: string;
  end: string;
  starting_capital: number;
  leverage: number;
  params: Record<string, unknown>;
  taker_fee_pct: number;
  slippage_pct: number;
  funding_rate_pct_per_8h: number;
  apply_funding: boolean;
  respect_daily_limits: boolean;
  walk_forward: boolean;
  walk_forward_folds: number;
  name?: string;
}

export const backtestService = {
  run: (payload: BacktestRunPayload) =>
    api.post<BacktestDetail>("/backtests/run", payload, 600_000),
  list: (limit = 50) => api.get<BacktestSummary[]>("/backtests", { limit }),
  detail: (id: number) => api.get<BacktestDetail>("/backtests/" + id),
  remove: (id: number) => api.delete<MessageResponse>("/backtests/" + id),
};

// ---------------------------------------------------------------------------
// Risk, settings and exchange
// ---------------------------------------------------------------------------
export const riskService = {
  get: () => api.get<{ config: RiskConfig; defaults: RiskConfig }>("/risk"),
  update: (config: RiskConfig) => api.put<{ config: RiskConfig }>("/risk", config),
};

export const settingsService = {
  get: () => api.get<SettingsResponse>("/settings"),
  updateTrading: (payload: Partial<TradingConfig>) =>
    api.put<MessageResponse>("/settings/trading", payload),
};

export const exchangeService = {
  status: () => api.get<SettingsResponse["exchange"]>("/exchange/status"),
  saveCredentials: (payload: {
    api_key: string;
    api_secret: string;
    market_type: string;
    testnet: boolean;
    withdrawal_disabled_confirmed: boolean;
  }) => api.post<MessageResponse>("/exchange/credentials", payload),
  deleteCredentials: () => api.delete<MessageResponse>("/exchange/credentials"),
  test: () => api.post<Record<string, unknown>>("/exchange/test"),
  refreshFilters: () => api.post<{ updated: number }>("/exchange/refresh-filters"),
  topSymbols: (limit = 10) =>
    api.get<TopSymbolResponse>("/exchange/top-symbols", { limit }),
  syncTopSymbols: (limit = 10) =>
    api.post<SyncTopSymbolsResponse>("/exchange/symbols/sync-top?limit=" + limit, undefined, 120_000),
};

export const tradingService = {
  liveChecklist: () => api.get<LiveChecklist>("/trading/live/checklist"),
  confirmLive: (payload: {
    confirmed: boolean;
    acknowledge_risk: boolean;
    acknowledge_no_profit_guarantee: boolean;
  }) => api.post<MessageResponse>("/trading/live/confirm", payload),
  resetPaper: (starting_balance: number, clear_history: boolean) =>
    api.post<MessageResponse>("/trading/paper/reset", { starting_balance, clear_history }),
};

// ---------------------------------------------------------------------------
// Market data
// ---------------------------------------------------------------------------
export const marketDataService = {
  candles: (symbol: string, timeframe: string, limit = 300, refresh = false) =>
    api.get<Candle[]>("/market-data/candles", { symbol, timeframe, limit, refresh }),
  ticker: (symbol?: string) =>
    api.get<Record<string, { price: number | null; age_seconds: number | null; stale: boolean }>>(
      "/market-data/ticker",
      { symbol },
    ),
  regime: () => api.get<Record<string, Record<string, unknown> | null>>("/market-data/regime"),
  timeframes: () => api.get<string[]>("/market-data/timeframes"),
};
