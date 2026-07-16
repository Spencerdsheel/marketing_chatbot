/**
 * Lead review console (S13.4). CLIENT_ADMIN + CLIENT_AGENT -- gated by the
 * new `requireAnyRole` (decision 2), colocated with this screen rather than
 * a `proxy.ts` route->role map (same seam as S13.2/S13.3).
 *
 * SERVER-FIRST (decision 1): this is an `async` server component that reads
 * filter/pagination state from the URL `searchParams`, fetches once per
 * navigation via `listLeads`, and renders the result. No client state, no
 * polling -- filtering and paging are plain URL navigations (a GET `<form>`
 * for the stage filter, `<Link>`s for Prev/Next) that change `searchParams`
 * and re-run this component.
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
import { LEAD_STAGES, listLeads } from "@/lib/leads";
import { LeadsFilter } from "@/app/(protected)/leads/leads-filter";
import { LeadsTable } from "@/app/(protected)/leads/leads-table";

interface LeadsPageProps {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

function firstValue(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function pageHref(page: number, stage: string | undefined): string {
  const query = new URLSearchParams();
  if (page > 1) query.set("page", String(page));
  if (stage) query.set("stage", stage);
  const qs = query.toString();
  return qs ? `/leads?${qs}` : "/leads";
}

export default async function LeadsPage({ searchParams }: LeadsPageProps) {
  await requireAnyRole("CLIENT_ADMIN", "CLIENT_AGENT");

  const params = await searchParams;
  const rawStage = firstValue(params.stage);
  const stage =
    rawStage && (LEAD_STAGES as readonly string[]).includes(rawStage) ? rawStage : undefined;
  const rawPage = Number.parseInt(firstValue(params.page) ?? "1", 10);
  const page = Number.isFinite(rawPage) && rawPage >= 1 ? rawPage : 1;

  const result = await listLeads({ page, stage });

  return (
    <div className="flex flex-1 flex-col items-center gap-4 p-8">
      <div className="w-full max-w-4xl">
        <Link href="/" className="text-sm text-muted-foreground hover:underline">
          ← Back to console
        </Link>
      </div>
      <Card className="w-full max-w-4xl">
        <CardHeader>
          <CardTitle>Lead review</CardTitle>
          <CardDescription>
            Showing your tenant&apos;s captured leads, newest first.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <LeadsFilter currentStage={stage} />

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
                    <Link href="/leads" className="underline">
                      Clear filter
                    </Link>
                  </>
                ) : result.total === 0 ? (
                  "No leads yet -- leads captured by your chatbot will appear here."
                ) : (
                  // A page beyond the last (e.g. a hand-edited URL) --
                  // degrade honestly instead of a blank/crashing table.
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
