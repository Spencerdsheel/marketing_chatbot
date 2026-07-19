/**
 * Renders the time-bucketed `series` as a table, restyled to Ink & Citron
 * (HANDOFF-SPEC.md §2 Tables: header row #f7f7f3 11.5px/600 uppercase
 * muted; rows 13px, `border-faint` dividers). Doubles as the accessible
 * text-alternative for `WeeklyBars` and `FunnelBars` (ui-ux-pro-max Charts
 * & Data: a table alternative for screen readers) -- exact per-bucket
 * counts, not just bar shapes.
 */
import type { AnalyticsOverview } from "@/lib/analytics";

function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function SeriesTable({ series }: { series: AnalyticsOverview["series"] }) {
  if (series.length === 0) {
    return (
      <p role="status" className="text-sm text-[#70716a]">
        No time-series data for this window.
      </p>
    );
  }

  return (
    <div className="overflow-hidden rounded-[14px] border border-[#e7e7e2]">
      <table className="w-full border-collapse text-[13px]">
        <caption className="sr-only">
          Conversation activity per bucket: exact counts backing the charts above.
        </caption>
        <thead>
          <tr className="bg-[#f7f7f3]">
            <th
              scope="col"
              className="px-4 py-2.5 text-left text-[11.5px] font-semibold tracking-wide text-[#70716a] uppercase"
            >
              Bucket start
            </th>
            <th
              scope="col"
              className="px-4 py-2.5 text-right text-[11.5px] font-semibold tracking-wide text-[#70716a] uppercase"
            >
              Conversations
            </th>
            <th
              scope="col"
              className="px-4 py-2.5 text-right text-[11.5px] font-semibold tracking-wide text-[#70716a] uppercase"
            >
              Answers
            </th>
            <th
              scope="col"
              className="px-4 py-2.5 text-right text-[11.5px] font-semibold tracking-wide text-[#70716a] uppercase"
            >
              Escalations
            </th>
            <th
              scope="col"
              className="px-4 py-2.5 text-right text-[11.5px] font-semibold tracking-wide text-[#70716a] uppercase"
            >
              Bookings
            </th>
          </tr>
        </thead>
        <tbody>
          {series.map((bucket) => (
            <tr key={bucket.bucketStart} className="border-t border-[#f0f0ea]">
              <td className="px-4 py-2.5 font-medium text-[#191a17]">
                {formatDate(bucket.bucketStart)}
              </td>
              <td className="px-4 py-2.5 text-right tabular-nums text-[#45463f]">
                {bucket.conversations}
              </td>
              <td className="px-4 py-2.5 text-right tabular-nums text-[#45463f]">
                {bucket.answers}
              </td>
              <td className="px-4 py-2.5 text-right tabular-nums text-[#45463f]">
                {bucket.escalations}
              </td>
              <td className="px-4 py-2.5 text-right tabular-nums text-[#45463f]">
                {bucket.bookings}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
