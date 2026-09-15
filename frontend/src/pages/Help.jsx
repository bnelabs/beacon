import PageContainer from '../components/ui/PageContainer'
import Card, { CardHeader, CardTitle, CardContent } from '../components/ui/Card'
import Badge from '../components/ui/Badge'

function Section({ title, badge, children }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>{title}</CardTitle>
          {badge && <Badge size="sm">{badge}</Badge>}
        </div>
      </CardHeader>
      <CardContent className="space-y-2 text-[13.5px] leading-relaxed text-bne-muted">
        {children}
      </CardContent>
    </Card>
  )
}

export default function Help() {
  return (
    <PageContainer
      eyebrow="Reference"
      title="Help"
      subtitle="What BEACON measures, what it refuses to measure, and where each answer lives."
    >
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Section title="How BEACON reads risk" badge="semantics">
          <p>
            The forecasting model emits a <strong className="text-bne-ink">standardized
            one-step-ahead prediction</strong> per monitored series. It is not a
            probability and not a 0–100 score; until calibration lands, risk levels
            are reported as <em>uncalibrated</em> rather than banded against an
            invented scale.
          </p>
          <p>
            Prediction jobs attach <strong className="text-bne-ink">split-conformal
            intervals</strong> (held-out rolling residuals per source) and a
            Student-t HMM <strong className="text-bne-ink">regime nowcast</strong>
            (calm/stress). Absence of either is reported as absence.
          </p>
        </Section>

        <Section title="Data governance" badge="fail-closed">
          <p>
            Every dataset passes a six-stage pipeline ending in a quality gate:
            row counts, required columns, missing ratios, freshness and a minimum
            score. Nothing is certified — and no prediction or backtest runs —
            without a verified attestation.
          </p>
          <p>
            Missing data is never invented: no synthetic fallbacks, no
            forward-filling, no zero-fills. Gaps stay gaps and are reported per
            source; the validator flags duplicates, future timestamps, outliers,
            gap runs, scale breaks and stale feeds.
          </p>
        </Section>

        <Section title="Jobs and validation" badge="walk-forward">
          <p>
            Training and backtesting run chronologically with embargoed
            walk-forward folds or CPCV, folded <em>within</em> each source so no
            fold trains on one indicator and tests on another. Metrics are
            seam-aware: direction is never scored across a source boundary.
          </p>
          <p>
            Every trained model is priced against persistence and AR(1) baselines
            that refit per fold while the model stays frozen — the conservative
            direction for a complexity claim.
          </p>
        </Section>

        <Section title="Systemic scenarios" badge="declared inputs">
          <p>
            Contagion analysis (Eisenberg–Noe clearing, coupled fire sales,
            liquidity spirals, Basel III translation) runs on
            <strong className="text-bne-ink"> declared balance sheets</strong>:
            exposures, endowments, holdings and margins you supply or upload
            (point-in-time vintaged). The platform never invents a balance sheet.
          </p>
          <p>
            Results state which inputs were present and which were absent; an
            absent channel renders as <em>not measured</em>, never as zero.
          </p>
        </Section>

        <Section title="Where things live">
          <ul className="list-disc space-y-1 pl-4">
            <li><strong className="text-bne-ink">Dashboard</strong> — activity, host status, data quality at a glance.</li>
            <li><strong className="text-bne-ink">Risk Map</strong> — geographic heat, markers and exposure arcs.</li>
            <li><strong className="text-bne-ink">Jobs / Results</strong> — every run, its metrics and its reports.</li>
            <li><strong className="text-bne-ink">Data Sources / Data Quality</strong> — feeds, certifications, anomalies.</li>
            <li><strong className="text-bne-ink">Models / Performance</strong> — catalogue, lift over baselines.</li>
          </ul>
        </Section>

        <Section title="Known limitations" badge="honest by design">
          <p>
            BEACON documents what it does not do in-repo: the reachability census
            lists every implemented-but-unwired module with its blocker and next
            step; the quant review records model limitations (symmetric tails, no
            jump diffusion, uncalibrated SDE) and the calibration roadmap.
          </p>
          <p>
            See <span className="font-mono text-xs">docs/QUANT_REVIEW_2026-09.md</span> and
            the census in <span className="font-mono text-xs">backend/tests/test_reachability.py</span>.
          </p>
        </Section>
      </div>
    </PageContainer>
  )
}
