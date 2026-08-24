/** Service layer: every backend endpoint used by the dashboard. */

import type {
  BacktestDetail,
  BacktestSummary,
  BotStatus,
  Candle,
  ComparisonResponse,
  CoverageEntry,
  EmergencyStopLevel,
  HealthReport,
  LiveChecklist,
  MarketDetail,
  MessageResponse,
  OverviewResponse,
  PositionView,
  RiskConfig,
  RotationConfig,
  RotationPlan,
  RotationRunView,
  RotationStatus,
  SelectionResult,
  SettingsResponse,
  SignalRecord,
  StrategySummary,
  SyncTopSymbolsResponse,
  SweepEstimate,
  SweepMatrix,
  SweepOptions,
  SweepResultsResponse,
  SweepView,
  SyncMarketsResponse,
  SystemEvent,
  TopSymbolResponse,
  UniverseResponse,
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
  close: (id: number, reason = "manual", percent = 100) =>
    api.post<MessageResponse>("/positions/" + id + "/close", { reason, percent }, 120_000),
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
  resetPaper: (payload: {
    starting_balance: number;
    clear_history: boolean;
    clear_equity_curve: boolean;
  }) => api.post<MessageResponse>("/trading/paper/reset", payload, 120_000),
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

// ---------------------------------------------------------------------------
// Market browser
// ---------------------------------------------------------------------------
export interface UniverseFilters {
  search?: string;
  sort?: string;
  descending?: boolean;
  limit?: number;
  offset?: number;
  min_quote_volume?: number;
  only_enabled?: boolean;
  include_non_crypto?: boolean;
  refresh?: boolean;
}

export const marketService = {
  universe: (filters: UniverseFilters = {}) =>
    api.get<UniverseResponse>("/markets/universe", { ...filters }, 120_000),
  detail: (symbol: string) => api.get<MarketDetail>("/markets/detail", { symbol }),
  coverage: (symbol?: string) =>
    api.get<{ coverage: Record<string, Record<string, CoverageEntry>>; markets: number }>(
      "/markets/data-coverage",
      { symbol },
    ),
  syncAll: (payload: { limit?: number; min_quote_volume?: number; include_non_crypto?: boolean }) =>
    api.post<SyncMarketsResponse>("/markets/sync", payload, 600_000),
  setEnabled: (payload: { symbols: string[]; enabled: boolean; replace?: boolean }) =>
    api.post<MessageResponse>("/markets/enable", payload),
};

// ---------------------------------------------------------------------------
// Matrix backtests
// ---------------------------------------------------------------------------
export interface SweepPayload {
  name?: string;
  strategy_keys: string[];
  symbols: string[];
  timeframes: string[];
  start: string;
  end: string;
  starting_capital: number;
  leverage: number;
  taker_fee_pct: number;
  slippage_pct: number;
  funding_rate_pct_per_8h: number;
  apply_funding: boolean;
  respect_daily_limits: boolean;
  download_missing: boolean;
  min_candles: number;
  symbol_source: string;
  top_n: number;
  min_quote_volume: number;
}

export interface SweepResultFilters {
  strategy?: string;
  symbol?: string;
  timeframe?: string;
  status?: string;
  min_trades?: number;
  sort?: string;
  descending?: boolean;
  limit?: number;
  offset?: number;
}

export const sweepService = {
  options: () => api.get<SweepOptions>("/sweeps/options"),
  estimate: (payload: SweepPayload) =>
    api.post<SweepEstimate>("/sweeps/estimate", payload, 180_000),
  start: (payload: SweepPayload) =>
    api.post<{ sweep: SweepView; estimate: SweepEstimate; message: string }>(
      "/sweeps",
      payload,
      180_000,
    ),
  list: (limit = 30) => api.get<SweepView[]>("/sweeps", { limit }),
  detail: (id: number) => api.get<SweepView>("/sweeps/" + id),
  results: (id: number, filters: SweepResultFilters = {}) =>
    api.get<SweepResultsResponse>("/sweeps/" + id + "/results", { ...filters }),
  matrix: (id: number, rows: string, columns: string, metric: string, minTrades = 20) =>
    api.get<SweepMatrix>("/sweeps/" + id + "/matrix", {
      rows,
      columns,
      metric,
      min_trades: minTrades,
    }),
  cancel: (id: number) => api.post<MessageResponse>("/sweeps/" + id + "/cancel"),
  remove: (id: number) => api.delete<MessageResponse>("/sweeps/" + id),
};

// ---------------------------------------------------------------------------
// Automatic rotation and strategy selection
// ---------------------------------------------------------------------------
export const rotationService = {
  get: () => api.get<RotationStatus>("/rotation"),
  update: (config: RotationConfig) => api.put<MessageResponse>("/rotation", config),
  preview: () => api.post<RotationPlan>("/rotation/preview", undefined, 180_000),
  runNow: (dryRun?: boolean) =>
    api.post<RotationRunView>(
      "/rotation/run" + (dryRun === undefined ? "" : "?dry_run=" + dryRun),
      undefined,
      180_000,
    ),
  history: (limit = 30) => api.get<RotationRunView[]>("/rotation/history", { limit }),
  selectStrategy: (sweepId: number) =>
    api.post<SelectionResult>("/rotation/select-strategy/" + sweepId, undefined, 180_000),
  applyStrategy: (payload: {
    strategy_key: string;
    timeframe: string;
    acknowledge_selection_bias: boolean;
  }) => api.post<MessageResponse>("/rotation/apply-strategy", payload),
};
