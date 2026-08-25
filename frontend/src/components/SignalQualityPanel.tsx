import { Panel } from "@/components/Panel";
import { Banner } from "@/components/StateViews";
import type { SignalQualityBucket, SignalQualityReport } from "@/types/api";
import { formatNumber, pnlClass } from "@/utils/format";

const FEATURE_LABELS: Record<string, string> = {
  confidence: "Sinyal güveni",
  adx: "Trend gücü (ADX)",
  atr_pct: "Oynaklık (ATR %)",
  volatility_rank: "Oynaklık sırası",
  volatility: "Oynaklık rejimi",
  trend: "Trend rejimi",
  market_regime: "Piyasa rejimi",
  side: "Yön",
  session: "Seans",
  stop_distance_pct: "Stop mesafesi",
};

function Row({ bucket }: { bucket: SignalQualityBucket }) {
  return (
    <tr>
      <td>{FEATURE_LABELS[bucket.feature] ?? bucket.feature}</td>
      <td className="muted">{bucket.label}</td>
      <td className="numeric">{bucket.trades}</td>
      <td className={"numeric " + pnlClass(bucket.expectancy_r)}>
        {formatNumber(bucket.expectancy_r, 4)}
      </td>
      <td className={"numeric " + pnlClass(bucket.edge_vs_all)}>
        {bucket.edge_vs_all > 0 ? "+" : ""}
        {formatNumber(bucket.edge_vs_all, 4)}
      </td>
      <td className="numeric">{formatNumber(bucket.win_rate_pct, 1)}%</td>
    </tr>
  );
}

/**
 * Which conditions preceded a profitable trade in this backtest.
 *
 * Deliberately shows the worst conditions next to the best. A list of only the
 * good ones reads like a recipe; seeing that the same feature has a profitable
 * and an unprofitable end makes it clear this is a split of one sample, and
 * that a thin slice of it proves nothing.
 */
export function SignalQualityPanel({ report }: { report: SignalQualityReport }) {
  if (!report || report.total_trades === 0) {
    return null;
  }

  const hasBuckets = report.best.length > 0 || report.worst.length > 0;

  return (
    <Panel
      title="Hangi koşullarda işe yaradı?"
      subtitle={
        report.total_trades +
        " işlem, filtresiz beklenti " +
        formatNumber(report.baseline_expectancy_r, 4) +
        " R"
      }
    >
      {!hasBuckets && (
        <Banner tone="info">
          Hiçbir koşulda yeterli işlem yok. Bu testten koşul bazında bir sonuç
          çıkarılamaz.
        </Banner>
      )}

      {hasBuckets && (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Koşul</th>
                  <th>Dilim</th>
                  <th className="numeric">İşlem</th>
                  <th className="numeric">Beklenti R</th>
                  <th className="numeric">Farkı</th>
                  <th className="numeric">Kazanma</th>
                </tr>
              </thead>
              <tbody>
                {report.best.slice(0, 6).map((b) => (
                  <Row key={b.feature + b.label} bucket={b} />
                ))}
                <tr>
                  <td colSpan={6} className="muted small" style={{ paddingTop: 14 }}>
                    En kötü koşullar
                  </td>
                </tr>
                {report.worst.slice(0, 5).map((b) => (
                  <Row key={"w" + b.feature + b.label} bucket={b} />
                ))}
              </tbody>
            </table>
          </div>

          <Banner tone="warning">
            Bu tablo tek bir örneklemin dilimleri. Yeterince dilimlerseniz her
            veride kârlı bir cep bulunur ve genelde gürültüdür. Bir koşulu ayar
            olarak benimsemeden önce, onu seçmek için kullanılmayan bir dönemde
            ölçün.
          </Banner>
        </>
      )}
    </Panel>
  );
}
