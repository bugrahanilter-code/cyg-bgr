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
    label: "İşlem başına risk (%)",
    hint: "Stop olursa riske giren varlık oranı. 0,5 muhafazakârdır.",
    step: 0.1,
    min: 0.05,
    max: 10,
  },
  {
    key: "max_position_notional_pct",
    label: "Maks. pozisyon (varlığın %'si)",
    hint: "Tek pozisyonun kaldıraç öncesi üst sınırı.",
    step: 5,
  },
  {
    key: "max_total_exposure_pct",
    label: "Maks. toplam maruziyet (%)",
    hint: "Tüm açık pozisyonların toplam değeri.",
    step: 10,
  },
  {
    key: "min_leverage",
    label: "Minimum kaldıraç",
    hint: "Her emre uygulanan taban. Borsa sınırı daha düşük olan markette, borsanın izin verdiği değer kullanılır; asla üstü değil.",
    step: 1,
    min: 1,
    max: 25,
  },
  { key: "max_leverage", label: "Maksimum kaldıraç", hint: "Her emre uygulanan katı üst sınır.", step: 1, min: 1, max: 25 },
  {
    key: "margin_buffer_pct",
    label: "Kullanılabilir teminat (%)",
    hint: "Serbest bakiyenin teminat olarak kullanılabilecek kısmı.",
    step: 5,
  },
];

const STOP_FIELDS: FieldSpec[] = [
  {
    key: "stop_loss_pct",
    label: "Stop distance (%)",
    hint: "Mod Sabit iken kullanılır; ayrıca bir strateji stopsuz sinyal ürettiğinde yedek olarak devreye girer.",
    step: 0.1,
    min: 0.1,
  },
  {
    key: "min_stop_distance_pct",
    label: "Minimum stop distance (%)",
    hint: "Sabit dışındaki her modda uygulanan güvenlik tabanı. 0 devre dışı bırakır.",
    step: 0.1,
    min: 0,
  },
  {
    key: "max_stop_distance_pct",
    label: "Maximum stop distance (%)",
    hint: "Güvenlik tavanı. %40 stop isteyen strateji hata yapıyordur, tercih değil. 0 devre dışı bırakır.",
    step: 0.5,
    min: 0,
  },
];

const TARGET_FIELDS: FieldSpec[] = [
  {
    key: "take_profit_pct",
    label: "Target distance (%)",
    hint: "Mod Sabit yüzde iken kullanılır.",
    step: 0.1,
    min: 0.1,
  },
  {
    key: "take_profit_r_multiple",
    label: "Target in R",
    hint: "Mod R katı iken kullanılır. 2, stopun iki katı uzaklıkta hedef demektir.",
    step: 0.1,
    min: 0.1,
  },
  {
    key: "min_risk_reward",
    label: "Minimum reward/risk",
    hint: "Hedefi stopuna göre fazla yakın olan girişleri reddeder. 0 kontrolü kapatır.",
    step: 0.1,
    min: 0,
  },
];

const TRAIL_FIELDS: FieldSpec[] = [
  {
    key: "trailing_stop_pct",
    label: "Trail distance (%)",
    hint: "Stopun en iyi fiyatı hangi mesafeden takip edeceği. Stratejinin kendi ATR takibi yoksa kullanılır.",
    step: 0.1,
    min: 0.1,
  },
  {
    key: "trailing_start_r",
    label: "Start trailing at (R)",
    hint: "Takibe ancak işlem bu kadar kâra geçince başlar. 0, ilk mumdan itibaren takip eder.",
    step: 0.1,
    min: 0,
  },
  {
    key: "break_even_at_r",
    label: "Break even at (R)",
    hint: "İşlem bu kadar öne geçtiğinde stopu girişe çeker. 0 kapatır. Riski kaldırır ama bazı kârlı işlemleri başabaşa çevirir.",
    step: 0.1,
    min: 0,
  },
];

const DAILY: FieldSpec[] = [
  {
    key: "daily_profit_target_pct",
    label: "Günlük kâr hedefi (%)",
    hint: "When reached, the bot stops opening new trades for the day.",
    step: 0.25,
  },
  {
    key: "daily_loss_limit_pct",
    label: "Günlük zarar limiti (%)",
    hint: "When reached, the platform goes into safe mode for the day.",
    step: 0.25,
  },
  { key: "max_trades_per_day", label: "Günlük maks. işlem", hint: "Overtrading protection.", step: 1 },
];

const STREAKS: FieldSpec[] = [
  {
    key: "max_consecutive_losses",
    label: "Üst üste maks. zarar",
    hint: "Trading pauses after this many losing trades in a row.",
    step: 1,
  },
  {
    key: "cooldown_minutes",
    label: "Bekleme süresi (dakika)",
    hint: "Waiting time after a loss before a new entry is allowed.",
    step: 5,
  },
  {
    key: "max_drawdown_pct",
    label: "Maksimum düşüş (%)",
    hint: "Trading stops when equity falls this far below its peak.",
    step: 1,
  },
  {
    key: "max_concurrent_positions",
    label: "Eşzamanlı maks. pozisyon",
    hint: "How many positions may be open at the same time.",
    step: 1,
  },
];

const QUALITY: FieldSpec[] = [
  {
    key: "min_signal_confidence",
    label: "Minimum sinyal güveni",
    hint: "Bu puanın altındaki sinyaller alınmaz (0-1). Ölçüm: 0,75 eşiğinde örneklem dışı beklenti -0,020R'den +0,088R'ye çıktı ve portföy getirisi %5'ten %24'e, düşüş %18'den %9'a gitti. Ayrıntı: docs/research/signal-quality.md",
    step: 0.05,
    min: 0,
    max: 1,
  },
  {
    key: "max_spread_pct",
    label: "Maksimum spread (%)",
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
      onSuccess: () => pushToast("Risk ayarları kaydedildi", "success"),
      onError: (mutationError) => pushToast(mutationError.message, "error"),
    },
  );

  if (isLoading || !config) {
    return error ? <ErrorState error={error} /> : <Loading />;
  }

  function setValue(key: keyof RiskConfig, value: number | boolean | string) {
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
          <h1>Risk</h1>
          <p>
            Risk Motoru her strateji sinyalini veto edebilir. Bu limitler tüm platformun
            güvenlik zarfıdır; varsayılanlar bilinçli olarak muhafazakârdır.
          </p>
        </div>
        <button
          type="button"
          className="btn btn-primary"
          disabled={save.isPending}
          onClick={() => config && save.mutate(config)}
        >
          Risk ayarlarını kaydet
        </button>
      </div>

      <Banner tone="info">
        Riski artırmak beklenen kârı artırmaz; er geç alacağınız zararın boyutunu artırır.
        Bot, günlük hedefe ulaşmak için kendiliğinden risk artırmaz.
      </Banner>

      <Panel title="İşlem başına">{renderFields(PER_TRADE)}</Panel>

      <Panel
        title="Zarar durdur (stop)"
        subtitle="İşlemin kesildiği yer. Pozisyon büyüklüğü bu mesafeden hesaplanır: geniş stop daha küçük pozisyon demektir, daha çok risk değil."
      >
        <div className="field">
          <label htmlFor="stop_loss_mode">Mode</label>
          <select
            id="stop_loss_mode"
            value={config.stop_loss_mode}
            onChange={(event) => setValue("stop_loss_mode", event.target.value)}
          >
            <option value="strategy">Use the strategy&apos;s own stop</option>
            <option value="fixed_pct">Fixed percentage from entry</option>
            <option value="bounded">Strategy stop, clamped into the band below</option>
          </select>
          <small>
            {config.stop_loss_mode === "strategy"
              ? "Her strateji kendi stopunu koyar, genelde ATR ile. Aşağıdaki bant yine güvenlik zarfı olarak uygulanır."
              : config.stop_loss_mode === "fixed_pct"
                ? "Strateji ne önerirse önersin her işlem aynı stop mesafesini kullanır."
                : "Strateji seçer, ama sonuç minimum ve maksimumun içine zorlanır."}
          </small>
        </div>
        {renderFields(STOP_FIELDS)}
      </Panel>

      <Panel
        title="Kâr al (hedef)"
        subtitle="İşlemin kârla kapatıldığı yer."
      >
        <div className="field">
          <label htmlFor="take_profit_mode">Mode</label>
          <select
            id="take_profit_mode"
            value={config.take_profit_mode}
            onChange={(event) => setValue("take_profit_mode", event.target.value)}
          >
            <option value="strategy">Use the strategy&apos;s own target</option>
            <option value="fixed_pct">Fixed percentage from entry</option>
            <option value="risk_multiple">Multiple of the risk taken (R)</option>
            <option value="none">No target: exit on the stop or a signal</option>
          </select>
          <small>
            {config.take_profit_mode === "none"
              ? "Trend sistemleri genelde birkaç büyük kazançtan para kazanır. Sabit hedef tam onları keser; kaldırmak getiriyi artırıp kazanma oranını düşürebilir."
              : config.take_profit_mode === "risk_multiple"
                ? "Hedef, gerçekten kullanılan stoptan ölçülür; genişletilen veya daraltılan stopu takip eder."
                : "Strateji ne önerirse önersin her işleme uygulanır."}
          </small>
        </div>
        {renderFields(TARGET_FIELDS)}
      </Panel>

      <Panel
        title="Takip eden stop ve başabaş"
        subtitle="Stop yalnızca kâr yönünde hareket eder, asla gevşetilmez."
      >
        <div className="field">
          <label>Trailing stop</label>
          <Toggle
            checked={config.trailing_stop_enabled}
            onChange={(value) => setValue("trailing_stop_enabled", value)}
            label={config.trailing_stop_enabled ? "On" : "Off"}
          />
          <small>
            A strategy that supplies its own ATR trail keeps it; this is the fallback
            for the ones that do not.
          </small>
        </div>
        {renderFields(TRAIL_FIELDS)}
      </Panel>
      <Panel title="Günlük limitler">{renderFields(DAILY)}</Panel>
      <Panel title="Zarar serisi ve düşüş">{renderFields(STREAKS)}</Panel>
      <Panel title="Piyasa kalite filtreleri">
        {config.min_signal_confidence < 0.7 && (
          <Banner tone="warning">
            <strong>
              Sinyal güveni eşiğiniz {config.min_signal_confidence.toFixed(2)} — ölçülen
              en iyi değer 0,75.
            </strong>{" "}
            8.980 işlem üzerinde, eşik veriye bakılmadan seçilip örneklem dışında
            ölçüldüğünde: filtresiz beklenti −0,020R, 0,75 eşiğinde +0,088R. Tek hesap
            üzerinde portföy getirisi %5,13 → %24,19, maksimum düşüş %18,3 → %9,0.
            Bu bir kâr garantisi değil; sinyallerin dörtte üçünü elemek pahasına elde
            edilen bir beklenti iyileşmesi.
          </Banner>
        )}
        {renderFields(QUALITY)}
        <div className="grid grid-3" style={{ marginTop: 10 }}>
          <div className="field">
            <label>Market başına tek pozisyon</label>
            <Toggle
              checked={config.one_position_per_symbol}
              onChange={(value) => setValue("one_position_per_symbol", value)}
            />
          </div>
          <div className="field">
            <label>Aşırı oynaklıkta engelle</label>
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
          Risk ayarlarını kaydet
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
