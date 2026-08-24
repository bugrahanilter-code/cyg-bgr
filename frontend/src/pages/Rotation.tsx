import { useEffect, useState } from "react";

import { Badge } from "@/components/Badge";
import { Panel } from "@/components/Panel";
import { Banner, ErrorState, Loading } from "@/components/StateViews";
import { Toggle } from "@/components/Toggle";
import { REFRESH_NORMAL, useApiMutation, usePolledQuery } from "@/hooks/useApi";
import { rotationService } from "@/services/tradingService";
import { useAppState } from "@/state/appStateContext";
import type { RotationConfig, RotationPlan, RotationRunView } from "@/types/api";
import { formatDateTime, formatNumber, pnlClass } from "@/utils/format";

function compactUsd(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  if (value >= 1e9) return "$" + (value / 1e9).toFixed(2) + "B";
  if (value >= 1e6) return "$" + (value / 1e6).toFixed(1) + "M";
  return "$" + value.toFixed(0);
}

/** The ranked candidate list, with the reason each rejection was rejected. */
function CandidateTable({ plan }: { plan: RotationPlan }) {
  const [showRejected, setGösterRejected] = useState(false);
  return (
    <>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Market</th>
              <th className="numeric">24s değişim</th>
              <th className="numeric">24s hacim</th>
              <th className="numeric">Spread</th>
            </tr>
          </thead>
          <tbody>
            {plan.selected.map((item) => (
              <tr key={item.symbol}>
                <td className="muted">{item.rank}</td>
                <td>
                  <strong>{item.symbol}</strong>
                  {plan.added.includes(item.symbol) && <Badge tone="success">NEW</Badge>}
                </td>
                <td className={"numeric " + pnlClass(item.change_24h_pct)}>
                  {item.change_24h_pct > 0 ? "+" : ""}
                  {formatNumber(item.change_24h_pct, 2)}%
                </td>
                <td className="numeric">{compactUsd(item.quote_volume_24h)}</td>
                <td className="numeric">
                  {item.spread_pct === null ? "-" : formatNumber(item.spread_pct, 3) + "%"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <button
        type="button"
        className="btn btn-sm btn-ghost"
        onClick={() => setGösterRejected((value) => !value)}
      >
        {showRejected ? "Gizle" : "Göster"} {plan.rejected.length} elenen aday
      </button>
      {showRejected && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Market</th>
                <th className="numeric">24s değişim</th>
                <th>Neden seçilmedi</th>
              </tr>
            </thead>
            <tbody>
              {plan.rejected.map((item) => (
                <tr key={item.symbol + item.reason}>
                  <td>{item.symbol}</td>
                  <td className={"numeric " + pnlClass(item.change_24h_pct ?? 0)}>
                    {formatNumber(item.change_24h_pct, 2)}%
                  </td>
                  <td className="muted">{item.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function RunSummary({ run }: { run: RotationRunView }) {
  return (
    <div className="stack">
      <div className="grid grid-4">
        <div className="mini-stat">
          <span>Çalıştı</span>
          <strong>{formatDateTime(run.ran_at)}</strong>
        </div>
        <div className="mini-stat">
          <span>Eklenen</span>
          <strong className="positive">{run.added.length}</strong>
        </div>
        <div className="mini-stat">
          <span>Çıkarılan</span>
          <strong className="negative">{run.removed.length}</strong>
        </div>
        <div className="mini-stat">
          <span>Sonrasında açık</span>
          <strong>{run.enabled_after}</strong>
        </div>
      </div>
      {run.dry_run && <Banner tone="info">Deneme modu: hiçbir şey değiştirilmedi.</Banner>}
      {run.held_open.length > 0 && (
        <Banner tone="warning">
          <strong>{run.held_open.join(", ")}</strong> listeden düştü ama açık pozisyonu olduğu
          için işleme açık kaldı. Pozisyon ortasında marketi kapatmak, motorun çıkışı
          yönetmesini engellerdi.
        </Banner>
      )}
      {run.error_message && <Banner tone="danger">{run.error_message}</Banner>}
    </div>
  );
}

export function RotationPage() {
  const { pushToast } = useAppState();
  const status = usePolledQuery(["rotation"], rotationService.get, REFRESH_NORMAL);
  const [form, setForm] = useState<RotationConfig | null>(null);
  const [plan, setPlan] = useState<RotationPlan | null>(null);

  useEffect(() => {
    if (status.data && form === null) {
      setForm(status.data.config);
    }
  }, [status.data, form]);

  const save = useApiMutation(
    () => rotationService.update(form as RotationConfig),
    [["rotation"], ["settings"]],
    {
      onSuccess: (response) => pushToast(response.message, "success"),
      onError: (error) => pushToast(error.message, "error"),
    },
  );

  const preview = useApiMutation(() => rotationService.preview(), [], {
    onSuccess: (result) => setPlan(result),
    onError: (error) => pushToast(error.message, "error"),
  });

  const runNow = useApiMutation(() => rotationService.runNow(), [["rotation"], ["settings"]], {
    onSuccess: (run) =>
      pushToast(
        "Döndürme bitti: +" + run.added.length + " / -" + run.removed.length + " market.",
        "success",
      ),
    onError: (error) => pushToast(error.message, "error"),
  });

  if (status.isLoading && !status.data) return <Loading />;
  if (status.error) return <ErrorState error={status.error} />;
  if (!status.data || !form) return <Loading />;

  const set = <K extends keyof RotationConfig>(key: K, value: RotationConfig[K]) =>
    setForm((current) => (current ? { ...current, [key]: value } : current));

  const numberField = (
    key: keyof RotationConfig,
    label: string,
    hint: string,
    step = 1,
  ) => (
    <div className="field" key={key}>
      <label htmlFor={"rot-" + key}>{label}</label>
      <input
        id={"rot-" + key}
        type="number"
        step={step}
        value={Number(form[key])}
        onChange={(event) => set(key, Number(event.target.value) as never)}
      />
      <small>{hint}</small>
    </div>
  );

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1>Otomasyon</h1>
          <p>24 saatte en çok yükselen marketleri otomatik olarak işleme açar, düzenli aralıklarla yeniler.</p>
        </div>
      </div>

      <Banner tone="warning">{status.data.warning}</Banner>

      <Panel
        title="Kurulum"
        subtitle={"Şu anda " + status.data.enabled_symbols.length + " market işleme açık"}
        actions={
          <Badge tone={form.enabled ? (form.dry_run ? "warning" : "success") : "neutral"}>
            {form.enabled ? (form.dry_run ? "DRY RUN" : "ACTIVE") : "OFF"}
          </Badge>
        }
      >
        <div className="grid grid-2">
          <Toggle
            checked={form.enabled}
            onChange={(value) => set("enabled", value)}
            label="Otomatik döndür"
          />
          <Toggle
            checked={form.dry_run}
            onChange={(value) => set("dry_run", value)}
            label="Deneme modu (sadece raporla, değiştirme)"
          />
        </div>

        <div className="grid grid-4">
          {numberField("top_n", "İşleme açılacak market sayısı", "24 saatlik değişime göre sıralanır.")}
          {numberField(
            "interval_minutes",
            "Yenileme aralığı (dakika)",
            "Her yenileme, değişen her markette bir çıkış ve bir giriş maliyeti öder.",
          )}
          {numberField(
            "min_quote_volume_24h",
            "Minimum 24s hacim ($)",
            "İnce hacimle yükselen coin emri kaldıramaz.",
            1_000_000,
          )}
          {numberField(
            "max_spread_pct",
            "Maksimum spread (%)",
            "Her girişte ve her çıkışta ödenir.",
            0.01,
          )}
          {numberField(
            "min_listing_age_days",
            "Minimum listelenme yaşı (gün)",
            "Geçen hafta listelenen coinin test edilecek geçmişi yok.",
          )}
          {numberField(
            "max_change_24h_pct",
            "Şundan büyük hareketleri yoksay (%)",
            "Bu büyüklükte hareket genelde listeleme olayıdır, trend değil.",
          )}
          {numberField(
            "cooldown_hours",
            "Çıkarma sonrası bekleme (saat)",
            "Sınırdaki coinin her saat girip çıkmasını engeller.",
          )}
          {numberField(
            "max_changes_per_run",
            "Çalışma başına maksimum çıkarma",
            "Tek bir volatil saat tüm defteri boşaltamaz.",
          )}
        </div>

        <div className="btn-row">
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => save.mutate(undefined as never)}
            disabled={save.isPending}
          >
            {save.isPending ? "Kaydediliyor…" : "Kaydet"}
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => preview.mutate(undefined as never)}
            disabled={preview.isPending}
          >
            {preview.isPending ? "Sıralanıyor…" : "Sıralamayı önizle"}
          </button>
          <button
            type="button"
            className="btn btn-warning"
            onClick={() => runNow.mutate(undefined as never)}
            disabled={runNow.isPending}
          >
            {runNow.isPending ? "Çalışıyor…" : "Şimdi döndür"}
          </button>
        </div>
      </Panel>

      {plan && (
        <Panel
          title="Şu anda ne yapardı"
          subtitle={plan.candidates_considered + " market kalite filtrelerini geçti"}
        >
          {plan.added.length === 0 && plan.removed.length === 0 ? (
            <Banner tone="success">İşleme açık set zaten sıralamayla uyuşuyor.</Banner>
          ) : (
            <Banner tone="info">
              <strong>{plan.added.join(", ") || "hiçbiri"}</strong> eklenir,{" "}
              <strong>{plan.removed.join(", ") || "hiçbiri"}</strong> çıkarılır.
            </Banner>
          )}
          <CandidateTable plan={plan} />
        </Panel>
      )}

      {status.data.last_run && (
        <Panel title="Son döndürme">
          <RunSummary run={status.data.last_run} />
        </Panel>
      )}

      {status.data.history.length > 1 && (
        <Panel title="Geçmiş">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Ne zaman</th>
                  <th>Tetikleyen</th>
                  <th>Eklenen</th>
                  <th>Çıkarılan</th>
                  <th>Korunan</th>
                  <th className="numeric">Sonrasında açık</th>
                </tr>
              </thead>
              <tbody>
                {status.data.history.map((run) => (
                  <tr key={run.id}>
                    <td>{formatDateTime(run.ran_at)}</td>
                    <td>
                      {run.triggered_by}
                      {run.dry_run && <Badge tone="neutral">DRY</Badge>}
                    </td>
                    <td className="positive">{run.added.join(", ") || "-"}</td>
                    <td className="negative">{run.removed.join(", ") || "-"}</td>
                    <td className="muted">{run.held_open.join(", ") || "-"}</td>
                    <td className="numeric">{run.enabled_after}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </div>
  );
}
