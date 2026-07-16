/**
 * Range + bucket control (S13.5.md decision 5). A plain GET `<form>` with
 * two native `<select>`s -- no client JS, no `select` primitive dependency
 * (decision 7), mirroring `leads/leads-filter.tsx` exactly. Submitting
 * navigates to `/analytics?range=...&bucket=...`, which re-runs the server
 * component. Server component -- no `"use client"` needed.
 */
import { ANALYTICS_BUCKETS, ANALYTICS_RANGES, type AnalyticsBucket, type AnalyticsRangeKey } from "@/lib/analytics";

const BUCKET_LABELS: Record<AnalyticsBucket, string> = {
  day: "Day",
  week: "Week",
};

export function AnalyticsRange({
  currentRange,
  currentBucket,
}: {
  currentRange: AnalyticsRangeKey;
  currentBucket: AnalyticsBucket;
}) {
  return (
    <form action="/analytics" method="get" className="flex flex-wrap items-end gap-3">
      <div className="flex flex-col gap-1">
        <label htmlFor="range" className="text-xs font-medium text-muted-foreground">
          Date range
        </label>
        <select
          id="range"
          name="range"
          defaultValue={currentRange}
          className="h-8 rounded-lg border border-input bg-transparent px-2.5 py-1 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
        >
          {ANALYTICS_RANGES.map((range) => (
            <option key={range.key} value={range.key}>
              {range.label}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="bucket" className="text-xs font-medium text-muted-foreground">
          Bucket
        </label>
        <select
          id="bucket"
          name="bucket"
          defaultValue={currentBucket}
          className="h-8 rounded-lg border border-input bg-transparent px-2.5 py-1 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
        >
          {ANALYTICS_BUCKETS.map((bucket) => (
            <option key={bucket} value={bucket}>
              {BUCKET_LABELS[bucket]}
            </option>
          ))}
        </select>
      </div>
      <button
        type="submit"
        className="h-8 rounded-lg border border-transparent bg-primary px-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/80"
      >
        Apply
      </button>
    </form>
  );
}
