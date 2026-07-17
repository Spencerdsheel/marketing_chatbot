/**
 * Per-client lead review screen (S13.7). Reuses S13.4's `LeadsFilter`/
 * `LeadsTable` as-is, parameterized by the route's `{tenantId}` (D1) so
 * `listLeads` targets the S12.7 PLATFORM_ADMIN super-user surface
 * `/admin/tenants/{tenantId}/leads` instead of the implicit `/admin/leads`.
 * Mirrors `leads/page.tsx`'s server-first architecture exactly (URL
 * searchParams drive filter/pagination, no client state).
 */
import Link from "next/link";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { LEAD_STAGES, listLeads } from "@/lib/leads";
import { LeadsFilter } from "@/app/(protected)/leads/leads-filter";
import { LeadsTable } from "@/app/(protected)/leads/leads-table";

interface ClientLeadsPageProps {
  params: Promise<{ tenantId: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

function firstValue(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function ClientLeadsPage({ params, searchParams }: ClientLeadsPageProps) {
  const { tenantId } = await params;
  const basePath = `/clients/${tenantId}/leads`;

  function pageHref(page: number, stage: string | undefined): string {
    const query = new URLSearchParams();
    if (page > 1) query.set("page", String(page));
    if (stage) query.set("stage", stage);
    const qs = query.toString();
    return qs ? `${basePath}?${qs}` : basePath;
  }

  const resolvedSearchParams = await searchParams;
  const rawStage = firstValue(resolvedSearchParams.stage);
  const stage =
    rawStage && (LEAD_STAGES as readonly string[]).includes(rawStage) ? rawStage : undefined;
  const rawPage = Number.parseInt(firstValue(resolvedSearchParams.page) ?? "1", 10);
  const page = Number.isFinite(rawPage) && rawPage >= 1 ? rawPage : 1;

  const result = await listLeads({ page, stage }, tenantId);

  return (
    <div className="flex flex-1 flex-col items-center gap-4 p-8">
      <Card className="w-full max-w-4xl">
        <CardHeader>
          <CardTitle>Lead review</CardTitle>
          <CardDescription>This client&apos;s captured leads, newest first.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <LeadsFilter currentStage={stage} basePath={basePath} />

          {result.status === "error" ? (
            <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
              {result.message}
              {result.correlationId ? (
                <span className="block text-xs text-destructive/80">
                  Correlation ID: {result.correlationId}
                </span>
              ) : null}
            </p>
          ) : result.items.length === 0 ? (
            <div className="flex flex-col gap-3">
              <p role="status" className="rounded-md border border-input bg-muted/50 p-4 text-sm">
                {result.total === 0 && stage ? (
                  <>
                    No leads match this filter.{" "}
                    <Link href={basePath} className="underline">
                      Clear filter
                    </Link>
                  </>
                ) : result.total === 0 ? (
                  "No leads yet -- leads captured by this client's chatbot will appear here."
                ) : (
                  "No leads on this page."
                )}
              </p>
              {result.total > 0 && result.offset > 0 ? (
                <Link href={pageHref(page - 1, stage)} className="text-sm underline">
                  Previous
                </Link>
              ) : null}
            </div>
          ) : (
            <>
              <LeadsTable items={result.items} />
              <div className="flex items-center justify-between text-sm text-muted-foreground">
                <span>
                  Showing {result.offset + 1}–{result.offset + result.items.length} of {result.total}
                </span>
                <div className="flex gap-3">
                  {result.offset > 0 ? (
                    <Link href={pageHref(page - 1, stage)} className="underline">
                      Previous
                    </Link>
                  ) : null}
                  {result.offset + result.limit < result.total ? (
                    <Link href={pageHref(page + 1, stage)} className="underline">
                      Next
                    </Link>
                  ) : null}
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
