/**
 * Per-client conversation analytics screen (S13.7). Reuses S13.5's
 * `AnalyticsRange`/`AnalyticsCards`/`DistributionBars`/`SeriesTable` as-is,
 * parameterized by the route's `{tenantId}` (D1) so `getAnalyticsOverview`
 * targets the S12.7 PLATFORM_ADMIN super-user surface
 * `/admin/tenants/{tenantId}/analytics/overview` instead of the implicit
 * `/admin/analytics/overview`. Mirrors `analytics/page.tsx`'s server-first
 * architecture exactly.
 */
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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

interface ClientAnalyticsPageProps {
  params: Promise<{ tenantId: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

function firstValue(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function ClientAnalyticsPage({
  params,
  searchParams,
}: ClientAnalyticsPageProps) {
  const { tenantId } = await params;
  const basePath = `/clients/${tenantId}/analytics`;

  const resolvedSearchParams = await searchParams;
  const rawRange = firstValue(resolvedSearchParams.range);
  const range: AnalyticsRangeKey =
    (ANALYTICS_RANGES as readonly { key: string }[]).some((r) => r.key === rawRange)
      ? (rawRange as AnalyticsRangeKey)
      : DEFAULT_RANGE_KEY;
  const rawBucket = firstValue(resolvedSearchParams.bucket);
  const bucket: AnalyticsBucket =
    rawBucket && (ANALYTICS_BUCKETS as readonly string[]).includes(rawBucket)
      ? (rawBucket as AnalyticsBucket)
      : DEFAULT_BUCKET;

  const result = await getAnalyticsOverview({ range, bucket }, tenantId);

  return (
    <div className="flex flex-1 flex-col items-center gap-4 p-8">
      <Card className="w-full max-w-4xl">
        <CardHeader>
          <CardTitle>Conversation analytics</CardTitle>
          <CardDescription>
            This client&apos;s conversation performance over the selected window.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-6">
          <AnalyticsRange currentRange={range} currentBucket={bucket} basePath={basePath} />

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
