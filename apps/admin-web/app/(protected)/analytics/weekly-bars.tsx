/**
 * Grouped bars over the resolved `series` (5b: "grouped weekly bars"),
 * restyled to Ink & Citron. The 5b mock groups "conversations" (dark bar)
 * against "leads" (citron bar) per week -- this backend's analytics
 * overview does not compute a lead count (that lives in `lib/leads.ts`,
 * out of scope for this module per the restyle brief), so the citron
 * series here is "answers" instead: `series[].answers`, a real per-bucket
 * count of bot turns that resolved with `decision = 'answer'`
 * (repository.py `_fetch_series`). The dark series is `series[].conversations`
 * (real, same source).
 *
 * Each bar pair carries a `title` (native tooltip) and a visually-hidden
 * text equivalent for the exact counts (ui-ux-pro-max Charts & Data: data
 * labels + non-color-only meaning + screen-reader alternative). The bucket
 * label under each pair already states its date, so color is reinforced by
 * the legend text, not the sole carrier of meaning.
 */
import type { AnalyticsOverview } from "@/lib/analytics";

function formatBucketLabel(iso: string, bucket: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  if (bucket === "week") {
    return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function WeeklyBars({ data }: { data: AnalyticsOverview }) {
  const { series } = data;

  if (series.length === 0) {
    return (
      <div className="flex flex-col gap-4 rounded-[14px] border border-[#e7e7e2] p-5">
        <div className="flex items-baseline gap-2.5">
          <span className="text-sm font-bold text-[#191a17]">Conversations vs. answers</span>
        </div>
        <p role="status" className="text-sm text-[#70716a]">
          No time-series data for this window.
        </p>
      </div>
    );
  }

  const maxValue = Math.max(...series.map((b) => Math.max(b.conversations, b.answers)), 1);

  return (
    <div className="flex flex-col gap-4 rounded-[14px] border border-[#e7e7e2] p-5">
      <div className="flex flex-wrap items-baseline gap-2.5">
        <span className="text-sm font-bold text-[#191a17]">Conversations vs. answers</span>
        <span className="flex items-center gap-3 text-[11px] text-[#96978e]">
          <span className="inline-flex items-center gap-1.5">
            <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-sm bg-[#3d3e38]" />
            conversations
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-sm bg-[#e4f222]" />
            answers (citron)
          </span>
        </span>
      </div>
      <div
        className="flex h-[180px] items-end gap-2.5"
        role="img"
        aria-label={`Conversations and answers per ${data.window.bucket}: ${series
          .map(
            (b) =>
              `${formatBucketLabel(b.bucketStart, data.window.bucket)} -- ${b.conversations} conversations, ${b.answers} answers`
          )
          .join("; ")}`}
      >
        {series.map((b) => {
          const convPct = Math.max((b.conversations / maxValue) * 100, b.conversations > 0 ? 4 : 0);
          const ansPct = Math.max((b.answers / maxValue) * 100, b.answers > 0 ? 4 : 0);
          return (
            <div
              key={b.bucketStart}
              className="flex h-full flex-1 flex-col items-center justify-end gap-1.5"
            >
              <div
                className="flex h-[160px] w-full items-end justify-center gap-1"
                title={`${formatBucketLabel(b.bucketStart, data.window.bucket)}: ${b.conversations} conversations, ${b.answers} answers`}
              >
                <div
                  className="w-3.5 rounded-[3px] bg-[#3d3e38]"
                  style={{ height: `${convPct}%` }}
                />
                <div
                  className="w-3.5 rounded-[3px] bg-[#e4f222]"
                  style={{ height: `${ansPct}%` }}
                />
              </div>
              <span className="text-[10.5px] text-[#96978e]">
                {formatBucketLabel(b.bucketStart, data.window.bucket)}
              </span>
            </div>
          );
        })}
      </div>
      {/* Screen-reader-only exact-value table, mirrors the aria-label. */}
      <table className="sr-only">
        <caption>Conversations and answers per {data.window.bucket}</caption>
        <thead>
          <tr>
            <th scope="col">Bucket</th>
            <th scope="col">Conversations</th>
            <th scope="col">Answers</th>
          </tr>
        </thead>
        <tbody>
          {series.map((b) => (
            <tr key={b.bucketStart}>
              <td>{formatBucketLabel(b.bucketStart, data.window.bucket)}</td>
              <td>{b.conversations}</td>
              <td>{b.answers}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
