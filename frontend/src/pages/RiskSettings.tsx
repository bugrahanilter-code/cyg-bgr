import { useEffect, useState } from "react";

import { Panel } from "@/components/Panel";
import { Banner, ErrorState, Loading } from "@/components/StateViews";
import { Toggle } from "@/components/Toggle";
import { useApiMutation, useOnceQuery } from "@/hooks/useApi";
import { riskService } from "@/services/tradingService";
import { useAppState } from "@/state/appStateContext";
import type { RiskConfig } from "@/types/api";

interface FieldSpec {
  key: keyof RiskConfig;
  label: string;
  hint: string;
  step?: number;
  min?: number;
  max?: number;
}

const PER_TRADE: FieldSpec[] = [
  {
    key: "risk_per_trade_pct",
    label: "Risk per trade (%)",
    hint: "Share of equity risked if the stop loss is hit. 0.5 is conservative.",
    step: 0.1,
    min: 0.05,
    max: 10,
  },
  {
    key: "max_position_notional_pct",
    label: "Max position size (% of equity)",
    hint: "Upper bound on a single position value, before leverage.",
    step: 5,
  },
  {
    key: "max_total_exposure_pct",
    label: "Max total exposure (%)",
    hint: "Combined value of every open position.",
    step: 10,
  },
  { key: "max_leverage", label: "Max leverage", hint: "Hard cap applied to every order.", step: 1, min: 1, max: 25 },
  {
    key: "margin_buffer_pct",
    label: "Usable margin (%)",
    hint: "Share of the free balance the platform may use as margin.",
    step: 5,
  },
];

const DAILY: FieldSpec[] = [
  {
    key: "daily_profit_target_pct",
    label: "Daily profit target (%)",
    hint: "When reached, the bot stops opening new trades for the day.",
    step: 0.25,
  },
  {
    key: "daily_loss_limit_pct",
    label: "Daily loss limit (%)",
    hint: "When reached, the platform goes into safe mode for the day.",
    step: 0.25,
  },
  { key: "max_trades_per_day", label: "Max trades per day", hint: "Overtrading protection.", step: 1 },
];

const STREAKS: FieldSpec[] = [
  {
    key: "max_consecutive_losses",
    label: "Max consecutive losses",
    hint: "Trading pauses after this many losing trades in a row.",
    step: 1,
  },
  {
    key: "cooldown_minutes",
    label: "Cooldown (minutes)",
    hint: "Waiting time after a loss before a new entry is allowed.",
    step: 5,
  },
  {
    key: "max_drawdown_pct",
    label: "Max drawdown (%)",
    hint: "Trading stops when equity falls this far below its peak.",
    step: 1,
  },
  {
    key: "max_concurrent_positions",
    label: "Max concurrent positions",
    hint: "How many positions may be open at the same time.",
    step: 1,
  },
];

const QUALITY: FieldSpec[] = [
  {
    key: "min_signal_confidence",
    label: "Minimum signal confidence",
    hint: "Signals below this score are ignored (0 to 1).",
    step: 0.05,
    min: 0,
    max: 1,
  },
  {
    key: "max_spread_pct",
    label: "Max spread (%)",
    hint: "Orders are refused when the bid/ask spread is wider than this.",
    step: 0.01,
  },
  { key: "taker_fee_pct", label: "Taker fee (%)", hint: "Used for sizing estimates.", step: 0.005 },
  { key: "slippage_pct", label: "Expected slippage (%)", hint: "Used for sizing estimates.", step: 0.005 },
];

export function RiskSettingsPage() {
  const { pushToast } = useAppState();
  const { data, isLoading, error } = useOnceQuery(["risk"], riskService.get);
  const [config, setConfig] = useState<RiskConfig | null>(null);

  useEffect(() => {
    if (data?.config && config === null) {
      setConfig(data.config);
    }
  }, [data, config]);

  const save = useApiMutation(
    (payload: RiskConfig) => riskService.update(payload),
    [["risk"], ["overview"], ["settings"]],
    {
      onSuccess: () => pushToast("Risk settings saved", "success"),
      onError: (mutationError) => pushToast(mutationError.message, "error"),
    },
  );

  if (isLoading || !config) {
    return error ? <ErrorState error={error} /> : <Loading />;
  }

  function setValue(key: keyof RiskConfig, value: number | boolean) {
    setConfig((current) => (current ? { ...current, [key]: value } : current));
  }

  function renderFields(fields: FieldSpec[]) {
    return (
      <div className="grid grid-3">
        {fields.map((field) => (
          <div className="field" key={String(field.key)}>
            <label htmlFor={String(field.key)}>{field.label}</label>
            <input
              id={String(field.key)}
              type="number"
              step={field.step ?? 0.1}
              min={field.min}
              max={field.max}
              value={Number(config?.[field.key] ?? 0)}
              onChange={(event) => setValue(field.key, Number(event.target.value))}
            />
            <small>{field.hint}</small>
          </div>
        ))}
      </div>
    );
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Risk settings</h1>
          <p>
            The Risk Engine can veto any strategy signal. These limits are the safety envelope
            of the whole platform; the defaults are deliberately conservative.
          </p>
        </div>
        <button
          type="button"
          className="btn btn-primary"
          disabled={save.isPending}
          onClick={() => config && save.mutate(config)}
        >
          Save risk settings
        </button>
      </div>

      <Banner tone="info">
        Increasing risk does not increase expected profit; it increases the size of the losses
        you will eventually take. The bot never raises risk on its own to reach the daily
        target.
      </Banner>

      <Panel title="Per trade">{renderFields(PER_TRADE)}</Panel>
      <Panel title="Daily limits">{renderFields(DAILY)}</Panel>
      <Panel title="Losing streaks and drawdown">{renderFields(STREAKS)}</Panel>
      <Panel title="Market quality filters">
        {renderFields(QUALITY)}
        <div className="grid grid-3" style={{ marginTop: 10 }}>
          <div className="field">
            <label>One position per symbol</label>
            <Toggle
              checked={config.one_position_per_symbol}
              onChange={(value) => setValue("one_position_per_symbol", value)}
            />
          </div>
          <div className="field">
            <label>Block on extreme volatility</label>
            <Toggle
              checked={config.block_on_extreme_volatility}
              onChange={(value) => setValue("block_on_extreme_volatility", value)}
            />
          </div>
          <div className="field">
            <label>Block on stale market data</label>
            <Toggle
              checked={config.block_on_stale_data}
              onChange={(value) => setValue("block_on_stale_data", value)}
            />
            <small>Strongly recommended. Trading on old prices is how accounts blow up.</small>
          </div>
        </div>
      </Panel>

      <div className="btn-row">
        <button
          type="button"
          className="btn btn-primary"
          disabled={save.isPending}
          onClick={() => config && save.mutate(config)}
        >
          Save risk settings
        </button>
        <button
          type="button"
          className="btn"
          onClick={() => data?.defaults && setConfig(data.defaults)}
        >
          Load the conservative defaults
        </button>
      </div>
    </>
  );
}
