import type { LeaderboardEntry, Recommendation } from "./types";

type ScoreBand = {
  label: string;
  min: number;
  max: number;
};

type DimensionMetric = {
  label: string;
  value: number | null;
  measured: number;
};

const SCORE_BANDS: ScoreBand[] = [
  { label: "0-49", min: 0, max: 49 },
  { label: "50-64", min: 50, max: 64 },
  { label: "65-79", min: 65, max: 79 },
  { label: "80-100", min: 80, max: 100 },
];

const RECOMMENDATIONS: Array<{
  key: Recommendation;
  label: string;
  className: string;
}> = [
  { key: "advance", label: "Advance", className: "analytics-segment-advance" },
  { key: "hold", label: "Hold", className: "analytics-segment-hold" },
  { key: "reject", label: "Reject", className: "analytics-segment-reject" },
];

function average(values: Array<number | null>): number | null {
  const measured = values.filter((value): value is number => value !== null);
  if (measured.length === 0) return null;
  return measured.reduce((total, value) => total + value, 0) / measured.length;
}

function dimensionMetric(
  label: string,
  values: Array<number | null>,
): DimensionMetric {
  return {
    label,
    value: average(values),
    measured: values.filter((value) => value !== null).length,
  };
}

function percentage(count: number, total: number): number {
  return total === 0 ? 0 : Math.round((count / total) * 100);
}

export function LeaderboardAnalytics({ entries }: { entries: LeaderboardEntry[] }) {
  if (entries.length === 0) return null;

  const distribution = SCORE_BANDS.map((band) => ({
    ...band,
    count: entries.filter(
      (entry) => entry.score >= band.min && entry.score <= band.max,
    ).length,
  }));
  const largestBand = Math.max(1, ...distribution.map((band) => band.count));

  const dimensions = [
    dimensionMetric(
      "Technical accuracy",
      entries.map((entry) => entry.technical_accuracy_score),
    ),
    dimensionMetric(
      "Project depth",
      entries.map((entry) => entry.project_depth_score),
    ),
    dimensionMetric(
      "Follow-up resilience",
      entries.map((entry) => entry.followup_resilience_score),
    ),
    dimensionMetric(
      "Consistency",
      entries.map((entry) => entry.consistency_score),
    ),
  ];

  const recommendationSegments = RECOMMENDATIONS.map((segment) => ({
    ...segment,
    count: entries.filter((entry) => entry.recommendation === segment.key).length,
  }));
  const flagged = entries.filter((entry) => entry.flagged).length;
  const clear = entries.length - flagged;

  return (
    <section className="leaderboard-analytics" aria-labelledby="leaderboard-analytics-title">
      <header className="analytics-heading">
        <div>
          <p className="insights-eyebrow">Job analytics</p>
          <h2 id="leaderboard-analytics-title">Scored interview patterns</h2>
        </div>
        <span>{entries.length} completed interview{entries.length === 1 ? "" : "s"}</span>
      </header>

      <div className="analytics-grid">
        <article className="analytics-panel">
          <div className="analytics-panel-heading">
            <div>
              <h3>Score spread</h3>
              <p>Composite score bands</p>
            </div>
            <strong>{Math.min(...entries.map((entry) => entry.score))}-{Math.max(...entries.map((entry) => entry.score))}</strong>
          </div>
          <div
            className="analytics-histogram"
            role="img"
            aria-label={`Composite score distribution: ${distribution
              .map((band) => `${band.label}, ${band.count}`)
              .join("; ")}`}
          >
            {distribution.map((band) => (
              <div className="analytics-column" key={band.label}>
                <strong>{band.count}</strong>
                <div className="analytics-column-plot">
                  {band.count > 0 && (
                    <span
                      className="analytics-column-fill"
                      style={{ height: `${(band.count / largestBand) * 100}%` }}
                    />
                  )}
                </div>
                <span>{band.label}</span>
              </div>
            ))}
          </div>
        </article>

        <article className="analytics-panel">
          <div className="analytics-panel-heading">
            <div>
              <h3>Dimension averages</h3>
              <p>Applicable scores only</p>
            </div>
          </div>
          <div className="analytics-metrics">
            {dimensions.map((dimension) => (
              <div className="analytics-metric" key={dimension.label}>
                <div>
                  <span>{dimension.label}</span>
                  <strong>{dimension.value === null ? "N/A" : Math.round(dimension.value)}</strong>
                </div>
                <div className="analytics-metric-track" aria-hidden="true">
                  {dimension.value !== null && (
                    <span style={{ width: `${dimension.value}%` }} />
                  )}
                </div>
                <small>{dimension.measured}/{entries.length} measured</small>
              </div>
            ))}
          </div>
        </article>

        <article className="analytics-panel analytics-mix-panel">
          <div className="analytics-panel-heading">
            <div>
              <h3>Decision mix</h3>
              <p>Recommendations and review</p>
            </div>
          </div>

          <div className="analytics-mix-group">
            <span>Recommendation</span>
            <div
              className="analytics-mix-track"
              role="img"
              aria-label={recommendationSegments
                .map((segment) => `${segment.label}, ${segment.count}`)
                .join("; ")}
            >
              {recommendationSegments.map((segment) =>
                segment.count > 0 ? (
                  <span
                    className={segment.className}
                    key={segment.key}
                    style={{ flexGrow: segment.count }}
                  />
                ) : null,
              )}
            </div>
            <ul className="analytics-legend">
              {recommendationSegments.map((segment) => (
                <li key={segment.key}>
                  <i className={segment.className} aria-hidden="true" />
                  <span>{segment.label}</span>
                  <strong>{segment.count}</strong>
                </li>
              ))}
            </ul>
          </div>

          <div className="analytics-mix-group">
            <span>Human review</span>
            <div
              className="analytics-mix-track"
              role="img"
              aria-label={`Needs review, ${flagged}; clear, ${clear}`}
            >
              {flagged > 0 && (
                <span className="analytics-segment-review" style={{ flexGrow: flagged }} />
              )}
              {clear > 0 && (
                <span className="analytics-segment-clear" style={{ flexGrow: clear }} />
              )}
            </div>
            <div className="analytics-review-counts">
              <span><strong>{percentage(flagged, entries.length)}%</strong> review</span>
              <span><strong>{percentage(clear, entries.length)}%</strong> clear</span>
            </div>
          </div>
        </article>
      </div>
    </section>
  );
}
