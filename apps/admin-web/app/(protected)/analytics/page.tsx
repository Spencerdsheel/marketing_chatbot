/**
 * Conversation analytics dashboard (S13.5). CLIENT_ADMIN + CLIENT_AGENT --
 * gated by the EXISTING `requireAnyRole` (decision 2), no new auth helper.
 *
 * SERVER-FIRST (decision 1): this is an `async` server component that reads
 * range/bucket state from the URL `searchParams`, fetches the aggregate
 * once per navigation via `getAnalyticsOverview`, and renders it. No client
 * state, no polling -- changing the range or bucket is a plain URL
 * navigation (a GET `<form>`) that re-runs this component. Mirrors
 * `leads/page.tsx`'s architecture exactly, adapted for an aggregate payload
 * instead of a paginated list.
 */
import Link from "next/link";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { requireAnyRole } from "@/lib/auth";
import {
  ANALYTICS_BUCKETS,
  ANALYTICS_RANGES,
  DEFAULT_BUCKET,
  DEFAULT_RANGE_KEY,
  getAnalyticsOverview,
  type AnalyticsBucket,
  type AnalyticsRangeKey,
} from "@/lib/analytics";
import { AnalyticsRange } from "@/app/(protected)/analytics/analytics-range";
import { AnalyticsCards } from "@/app/(protected)/analytics/analytics-cards";
import { DistributionBars } from "@/app/(protected)/analytics/distribution-bars";
import { SeriesTable } from "@/app/(protected)/analytics/series-table";

interface AnalyticsPageProps {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

function firstValue(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function AnalyticsPage({ searchParams }: AnalyticsPageProps) {
  await requireAnyRole("CLIENT_ADMIN", "CLIENT_AGENT");

  const params = await searchParams;
  const rawRange = firstValue(params.range);
  const range: AnalyticsRangeKey =
    (ANALYTICS_RANGES as readonly { key: string }[]).some((r) => r.key === rawRange)
      ? (rawRange as AnalyticsRangeKey)
      : DEFAULT_RANGE_KEY;
  const rawBucket = firstValue(params.bucket);
  const bucket: AnalyticsBucket =
    rawBucket && (ANALYTICS_BUCKETS as readonly string[]).includes(rawBucket)
      ? (rawBucket as AnalyticsBucket)
      : DEFAULT_BUCKET;

  const result = await getAnalyticsOverview({ range, bucket });

  return (
    <div className="flex flex-1 flex-col items-center gap-4 p-8">
      <div className="w-full max-w-4xl">
        <Link href="/" className="text-sm text-muted-foreground hover:underline">
          ← Back to console
        </Link>
      </div>
      <Card className="w-full max-w-4xl">
        <CardHeader>
          <CardTitle>Conversation analytics</CardTitle>
          <CardDescription>
            Your tenant&apos;s conversation performance over the selected window.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-6">
          <AnalyticsRange currentRange={range} currentBucket={bucket} />

          {result.status === "error" ? (
            <p
              role="alert"
              className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive"
            >
              {result.message}
              {result.correlationId ? (
                <span className="block text-xs text-destructive/80">
                  Correlation ID: {result.correlationId}
                </span>
              ) : null}
            </p>
          ) : result.data.totals.conversations === 0 ? (
            <p role="status" className="rounded-md border border-input bg-muted/50 p-4 text-sm">
              No conversation activity in this window yet.
            </p>
          ) : (
            <>
              <AnalyticsCards data={result.data} />
              <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
                <DistributionBars title="Intent distribution" data={result.data.intentDistribution} />
                <DistributionBars
                  title="Decision distribution"
                  data={result.data.decisionDistribution}
                />
              </div>
              <div className="flex flex-col gap-2">
                <h3 className="text-sm font-medium">Time series</h3>
                <SeriesTable series={result.data.series} />
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
