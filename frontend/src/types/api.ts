/**
 * Types mirroring the backend API payloads.
 *
 * The frontend contains no trading logic: it only renders what the backend
 * computes. Keeping the contract in one file makes it obvious when the API
 * changes.
 */

export type TradingMode = "backtest" | "paper" | "live";
export type RiskLevel = "safe" | "medium" | "risky";
export type SignalType = "LONG" | "SHORT" | "HOLD" | "CLOSE";
export type HealthStatus = "OK" | "DEGRADED" | "DOWN" | "UNKNOWN";
export type EmergencyStopLevel =
  | "NONE"
  | "HALT_NEW_ENTRIES"
  | "CLOSE_ALL_POSITIONS"
  | "FULL_STOP";

export interface MessageResponse {
  ok: boolean;
  message: string;
  details?: Record<string, unknown>;
}

export interface BotStatus {
  status: string;
  mode: TradingMode;
  emergency_stop_level: EmergencyStopLevel;
  live_trading_confirmed: boolean;
  reconciliation_status: string;
  last_heartbeat: string | null;
  engine: Record<string, unknown>;
}

export interface HealthComponent {
  name: string;
  status: HealthStatus;
  detail: string;
  [key: string]: unknown;
}

export interface HealthReport {
  overall: HealthStatus;
  checked_at: string;
  components: HealthComponent[];
  bot_status: string;
  mode: string;
  emergency_stop_level: EmergencyStopLevel;
  live_trading_confirmed: boolean;
  last_heartbeat: string | null;
  last_market_data: string | null;
  engine: Record<string, unknown>;
}

export interface PositionView {
  id: number;
  uid: string;
  symbol: string;
  side: "LONG" | "SHORT";
  status: string;
  strategy: string;
  quantity: number;
  entry_price: number;
  current_price: number;
  stop_loss: number | null;
  take_profit: number | null;
  trailing_stop: number | null;
  leverage: number;
  margin: number;
  liquidation_price: number | null;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  /** Raw price difference, before any cost. */
  unrealized_pnl_gross: number;
  entry_fees_paid: number;
  funding_paid: number;
  estimated_exit_fee: number;
  total_costs: number;
  /** Price move still needed just to cover the round trip. */
  breakeven_move_pct: number;
  /** How far the market moved, ignoring leverage. */
  price_change_pct: number;
  /** What that move did to the margin committed. Leverage multiplies this. */
  return_on_margin_pct: number;
  /** Position value right now, in quote currency. */
  current_notional: number;
  notional: number;
  opened_at: string;
  market_regime: string;
  signal_confidence: number;
  entry_reason: string;
  mode: TradingMode;
}

export interface TradeView {
  id: number;
  uid: string;
  symbol: string;
  strategy_key: string;
  mode: TradingMode;
  timeframe: string;
  side: "LONG" | "SHORT";
  quantity: number;
  entry_price: number;
  exit_price: number;
  leverage: number;
  stop_loss: number | null;
  take_profit: number | null;
  notional: number;
  opened_at: string;
  closed_at: string;
  duration_seconds: number;
  gross_pnl: number;
  fees: number;
  funding: number;
  slippage_cost: number;
  net_pnl: number;
  return_pct: number;
  equity_after: number | null;
  is_win: boolean;
  signal_confidence: number;
  market_regime: string;
  entry_reason: string;
  exit_reason: string;
  backtest_id: number | null;
}

export interface OverviewResponse {
  generated_at: string;
  bot: {
    status: string;
    mode: TradingMode;
    emergency_stop_level: EmergencyStopLevel;
    emergency_stop_active: boolean;
    live_trading_confirmed: boolean;
    halt_reason: string;
    last_heartbeat: string | null;
    engine: Record<string, unknown>;
  };
  account: {
    balance: number;
    available_balance: number;
    used_margin: number;
    unrealized_pnl: number;
    equity: number;
  };
  pnl: {
    realized_today: number;
    daily_return_pct: number;
    weekly: number;
    monthly: number;
    unrealized: number;
    fees_today: number;
    funding_today: number;
  };
  risk: {
    daily_profit_target_pct: number;
    daily_loss_limit_pct: number;
    daily_target_progress_pct: number;
    daily_target_reached: boolean;
    daily_loss_limit_reached: boolean;
    current_drawdown_pct: number;
    max_drawdown_pct: number;
    trades_today: number;
    max_trades_per_day: number;
    consecutive_losses: number;
    max_consecutive_losses: number;
    open_positions: number;
    max_concurrent_positions: number;
    blocked_reasons: string[];
  };
  positions: PositionView[];
  recent_trades: Array<Record<string, unknown>>;
  equity_curve: Array<{ time: string; equity: number }>;
  symbols: string[];
  prices: Record<string, number | null>;
}

export interface StrategySummary {
  key: string;
  name: string;
  family: string;
  risk_level: RiskLevel;
  description: string;
  enabled: boolean;
  params: Record<string, unknown>;
  default_params: Record<string, unknown>;
  param_schema: JsonSchema;
  current_signal: SignalPayload | null;
  performance: PerformanceSummary;
}

export interface JsonSchema {
  properties?: Record<string, JsonSchemaProperty>;
  [key: string]: unknown;
}

export interface JsonSchemaProperty {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
  anyOf?: Array<{ type?: string }>;
}

export interface SignalPayload {
  uid: string;
  symbol: string;
  timeframe: string;
  strategy: string;
  signal: SignalType;
  confidence: number;
  candle_open_time: number;
  timestamp: string;
  entry: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  risk_reward: number | null;
  explanation: string;
  indicators: Record<string, number | null>;
  regime: RegimePayload | null;
}

export interface RegimePayload {
  regime: string;
  trend: string;
  volatility: string;
  adx: number | null;
  atr: number | null;
  atr_pct: number | null;
  volatility_rank: number | null;
  realized_volatility: number | null;
}

export interface PerformanceSummary {
  trades: number;
  wins: number;
  losses: number;
  win_rate_pct: number;
  net_pnl: number;
  gross_pnl: number;
  fees: number;
  funding: number;
  profit_factor: number | null;
  expectancy: number;
  average_win: number;
  average_loss: number;
  max_drawdown_pct: number;
  max_consecutive_losses: number;
  average_duration_seconds: number;
  average_return_pct: number;
}

export interface ComparisonResponse {
  mode: TradingMode;
  symbols: string[];
  rows: Array<{
    strategy: string;
    overall: PerformanceSummary;
    by_symbol: Array<PerformanceSummary & { symbol: string }>;
  }>;
}

export interface RiskConfig {
  risk_per_trade_pct: number;
  max_position_notional_pct: number;
  max_total_exposure_pct: number;
  min_leverage: number;
  max_leverage: number;
  /** strategy | fixed_pct | bounded */
  stop_loss_mode: string;
  stop_loss_pct: number;
  min_stop_distance_pct: number;
  max_stop_distance_pct: number;
  /** strategy | fixed_pct | risk_multiple | none */
  take_profit_mode: string;
  take_profit_pct: number;
  take_profit_r_multiple: number;
  min_risk_reward: number;
  trailing_stop_enabled: boolean;
  trailing_stop_pct: number;
  trailing_start_r: number;
  break_even_at_r: number;
  margin_buffer_pct: number;
  daily_profit_target_pct: number;
  daily_loss_limit_pct: number;
  max_trades_per_day: number;
  max_consecutive_losses: number;
  cooldown_minutes: number;
  max_drawdown_pct: number;
  max_concurrent_positions: number;
  one_position_per_symbol: boolean;
  min_signal_confidence: number;
  max_spread_pct: number;
  block_on_extreme_volatility: boolean;
  block_on_stale_data: boolean;
  taker_fee_pct: number;
  slippage_pct: number;
}

export interface TradingConfig {
  mode: TradingMode;
  market_type: "spot" | "futures";
  timeframe: string;
  higher_timeframe: string;
  leverage: number;
  enabled_symbols: string[];
  enabled_strategies: Record<string, boolean>;
  auto_start_engine: boolean;
}

export interface SettingsResponse {
  risk: RiskConfig;
  trading: TradingConfig;
  notifications: Record<string, boolean>;
  exchange: ExchangeStatus;
  environment: {
    app_env: string;
    live_trading_enabled_in_env: boolean;
    default_timeframe: string;
    supported_symbols: string[];
    paper_starting_balance: number;
  };
}

export interface ExchangeStatus {
  configured: boolean;
  source: string;
  api_key_masked: string;
  market_type: string;
  testnet: boolean;
  last_tested_at: string | null;
  last_test_ok: boolean;
  last_test_message: string;
  withdrawal_permission_warning: boolean;
  connection_status?: string;
  connection_error?: string;
  gateway?: string;
  security_notice?: string;
}

export interface BacktestSummary {
  id: number;
  uid: string;
  name: string;
  strategy_key: string;
  symbol: string;
  timeframe: string;
  start_date: string;
  end_date: string;
  starting_capital: number;
  status: string;
  error_message: string | null;
  params: Record<string, unknown>;
  cost_model: Record<string, unknown>;
  duration_seconds: number;
  candles_used: number;
  created_at: string;
  completed_at: string | null;
}

export interface BacktestDetail {
  backtest: BacktestSummary;
  metrics: Record<string, number | string | null>;
  equity_curve: Array<{ time: string; timestamp_ms: number; equity: number; balance: number }>;
  drawdown_curve: Array<{ time: string; drawdown_pct: number }>;
  monthly_returns: Array<{ month: string; return_pct: number; start_equity: number; end_equity: number }>;
  trade_distribution: {
    histogram?: Array<{ from: number; to: number; count: number }>;
    by_symbol?: Array<{ label: string; count: number; net_pnl: number; win_rate_pct: number }>;
    by_exit_reason?: Array<{ label: string; count: number; net_pnl: number; win_rate_pct: number }>;
  };
  walk_forward: WalkForwardResult | null;
  trades: TradeView[];
}

export interface WalkForwardResult {
  folds: Array<{
    fold: number;
    best_params: Record<string, unknown>;
    in_sample: Record<string, number>;
    out_of_sample: Record<string, number>;
  }>;
  out_of_sample_summary: Record<string, number | null>;
  objective: string;
  warning: string;
}

export interface SystemEvent {
  id: number;
  severity: string;
  category: string;
  message: string;
  mode: string;
  symbol: string;
  details: Record<string, unknown>;
  created_at: string;
}

export interface Candle {
  open_time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface LiveChecklist {
  env_flag_enabled: boolean;
  confirmed: boolean;
  ready: boolean;
  items: Array<{ key: string; label: string; done: boolean }>;
  warning: string;
}

/** A signal row as stored in the database (returned by GET /signals). */
export interface SignalRecord {
  id: number;
  uid: string;
  symbol: string;
  strategy_key: string;
  timeframe: string;
  mode: TradingMode;
  candle_open_time: number;
  signal_type: SignalType;
  confidence: number;
  market_regime: string;
  trend_regime: string;
  volatility_regime: string;
  entry_price: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  explanation: string;
  indicators: Record<string, number | null>;
  status: string;
  rejection_codes: string[];
  rejection_details: string;
  created_at: string;
}

/** A market ranked by 24 hour volume (GET /exchange/top-symbols). */
export interface TopSymbol {
  symbol: string;
  base_asset: string;
  quote_asset: string;
  quote_volume_24h: number;
  last_price: number;
  change_24h_pct: number;
}

export interface TopSymbolResponse {
  symbols: TopSymbol[];
  note: string;
}

export interface SyncTopSymbolsResponse {
  discovered: TopSymbol[];
  added: string[];
  updated: string[];
  message: string;
}

// ---------------------------------------------------------------------------
// Market browser (GET /markets/universe)
// ---------------------------------------------------------------------------

/**
 * One market with its 24 hour statistics.
 *
 * Fields prefixed `tv_` come from the TradingView screener and are context for
 * a human choosing what to trade. No strategy, risk check or order reads them.
 */
export interface MarketRow {
  symbol: string;
  base_asset: string;
  quote_asset: string;
  is_crypto: boolean;
  last_price: number;
  open_24h: number;
  high_24h: number;
  low_24h: number;
  change_24h_pct: number;
  change_24h_abs: number;
  base_volume_24h: number;
  quote_volume_24h: number;
  weighted_average: number;
  bid: number | null;
  ask: number | null;
  spread_pct: number | null;
  range_position_pct: number | null;
  maint_margin_pct: number | null;
  /** Taker fee in and out, slippage in and out, plus the live spread. */
  round_trip_cost_pct: number;
  volume_rank: number;
  /** crypto | commodity | forex. */
  kind: string;
  /** False for research-only markets no exchange here can fill. */
  tradable: boolean;
  /** True when this is one of the gold/FX reference markets. */
  reference: boolean;
  session: string;
  history_source: string;
  notes: string;
  enabled: boolean;
  in_database: boolean;
  tv_symbol: string;
  tv_rating: number | null;
  tv_rating_label: string;
  tv_rsi: number | null;
  tv_atr: number | null;
  tv_relative_volume: number | null;
  tv_volatility_daily_pct: number | null;
  atr_pct: number | null;
}

export interface SourceStatus {
  ok: boolean;
  markets: number;
  error: string | null;
}

export interface UniverseResponse {
  rows: MarketRow[];
  total: number;
  offset: number;
  limit: number;
  enabled_count: number;
  known_count: number;
  sources: Record<string, SourceStatus>;
  age_seconds: number;
  sortable_fields: string[];
  note: string;
}

export interface CoverageEntry {
  candles: number;
  from: string | null;
  to: string | null;
}

/** Extra metadata carried only by the gold and FX reference markets. */
export interface ReferenceMarketInfo {
  kind: string;
  description: string;
  session: string;
  tradable: boolean;
  history_source: string;
  history_limits: Record<string, string>;
  has_volume: boolean;
  typical_round_trip_cost_pct: number;
  notes: string;
  /** Strategies gated on volume: they cannot produce a signal here at all. */
  untestable_strategies: string[];
  /** Strategies that still run but with one scoring input permanently zero. */
  degraded_strategies: string[];
}

export interface MarketDetail {
  market: MarketRow;
  enabled: boolean;
  in_database: boolean;
  filters: Record<string, number | string | null> | null;
  regime: Record<string, unknown> | null;
  reference: ReferenceMarketInfo | null;
  data_coverage: Record<string, CoverageEntry>;
  live_price: number | null;
}

export interface SyncMarketsResponse {
  added: string[];
  updated: string[];
  total_available: number;
  message: string;
}

// ---------------------------------------------------------------------------
// Matrix backtests (sweeps)
// ---------------------------------------------------------------------------

/** What a requested grid will cost before it is started. */
export interface SweepEstimate {
  cells: number;
  strategies: number;
  symbols: number;
  timeframes: number;
  total_candles: number;
  bar_evaluations: number;
  estimated_seconds: number;
  estimated_minutes: number;
  estimated_hours: number;
  estimated_download_requests: number;
  estimated_storage_mb: number;
  warnings: string[];
  symbols_preview?: string[];
  symbol_count?: number;
}

export interface SweepSummary {
  completed_cells: number;
  cells_with_enough_trades: number;
  profitable_cells: number;
  profitable_pct: number;
  beat_buy_and_hold: number;
  beat_buy_and_hold_pct: number;
  positive_expectancy_r_cells: number;
  average_expectancy_r: number;
  min_trades_for_inclusion: number;
}

/** One cell of the grid: one strategy on one market and timeframe. */
export interface SweepRunRow {
  id: number;
  strategy_key: string;
  symbol: string;
  timeframe: string;
  status: string;
  total_trades: number;
  net_pnl: number;
  return_pct: number;
  buy_hold_return_pct: number;
  excess_return_pct: number;
  win_rate_pct: number;
  profit_factor: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  max_drawdown_pct: number;
  expectancy: number;
  expectancy_r: number;
  total_fees: number;
  candles_used: number;
  duration_seconds: number;
  error_message: string | null;
}

export interface SweepView {
  id: number;
  uid: string;
  name: string;
  status: string;
  strategy_keys: string[];
  symbols: string[];
  timeframes: string[];
  symbol_count: number;
  start_date: string;
  end_date: string;
  starting_capital: number;
  leverage: number;
  cost_model: Record<string, number | boolean>;
  total_runs: number;
  completed_runs: number;
  failed_runs: number;
  skipped_runs: number;
  finished_runs: number;
  progress_pct: number;
  current_task: string;
  started_at: string | null;
  completed_at: string | null;
  duration_seconds: number;
  error_message: string | null;
  cancel_requested: boolean;
  is_running: boolean;
  leaderboard?: SweepRunRow[];
  summary?: SweepSummary;
}

export interface SweepMatrixCell {
  value: number | null;
  cells: number;
  trades: number;
}

export interface SweepMatrix {
  metric: string;
  rows: string[];
  columns: string[];
  cells: Record<string, Record<string, SweepMatrixCell>>;
  min_trades: number;
}

export interface SweepOptions {
  strategies: string[];
  timeframes: string[];
  symbol_sources: string[];
  symbols_in_database: number;
  enabled_symbols: string[];
  throughput_bars_per_second: number;
}

export interface SweepResultsResponse {
  rows: SweepRunRow[];
  total: number;
  offset: number;
  limit: number;
}

// ---------------------------------------------------------------------------
// Automatic rotation into the top 24 hour movers
// ---------------------------------------------------------------------------
export interface RotationConfig {
  enabled: boolean;
  dry_run: boolean;
  top_n: number;
  interval_minutes: number;
  min_quote_volume_24h: number;
  max_spread_pct: number;
  min_listing_age_days: number;
  max_change_24h_pct: number;
  min_change_24h_pct: number;
  cooldown_hours: number;
  max_changes_per_run: number;
}

export interface RotationCandidate {
  symbol: string;
  rank?: number;
  change_24h_pct: number;
  quote_volume_24h: number;
  spread_pct: number | null;
  last_price?: number;
}

export interface RotationRejection {
  symbol: string;
  reason: string;
  change_24h_pct: number | null;
  quote_volume_24h: number | null;
}

export interface RotationRunView {
  id: number;
  ran_at: string;
  dry_run: boolean;
  triggered_by: string;
  selected: RotationCandidate[];
  added: string[];
  removed: string[];
  unchanged: string[];
  /** Markets kept enabled because a position is still open on them. */
  held_open: string[];
  rejected: RotationRejection[];
  candidates_considered: number;
  enabled_after: number;
  duration_seconds: number;
  error_message: string | null;
}

export interface RotationPlan {
  selected: RotationCandidate[];
  rejected: RotationRejection[];
  added: string[];
  removed: string[];
  held_open: string[];
  unchanged: string[];
  final_symbols: string[];
  candidates_considered: number;
  config: RotationConfig;
  warning: string;
}

export interface RotationStatus {
  config: RotationConfig;
  defaults: RotationConfig;
  enabled_symbols: string[];
  last_run: RotationRunView | null;
  history: RotationRunView[];
  warning: string;
}

/** One strategy/timeframe combination aggregated across markets. */
export interface SelectionCandidate {
  strategy_key: string;
  timeframe: string;
  markets: number;
  markets_profitable: number;
  profitable_pct: number;
  total_trades: number;
  median_expectancy_r: number;
  mean_expectancy_r: number;
  median_profit_factor: number;
  median_return_pct: number;
  median_drawdown_pct: number;
  median_excess_vs_hold_pct: number;
  worst_market_return_pct: number;
  passed: boolean;
  failures: string[];
}

export interface SelectionResult {
  sweep_id: number;
  sweep_name: string;
  verdict: "QUALIFIED" | "NO_QUALIFYING_COMBINATION";
  winner: SelectionCandidate | null;
  qualifying_count: number;
  combinations_tested: number;
  ranked: SelectionCandidate[];
  selection_bias_note: string;
  next_step: string;
  validation_plan?: Record<string, unknown>;
}
