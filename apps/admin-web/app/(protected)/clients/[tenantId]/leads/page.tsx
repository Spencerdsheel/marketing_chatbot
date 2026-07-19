/**
 * Per-client lead review screen (S13.7), restyled alongside `leads/page.tsx`
 * to the 4b screen. Reuses the same restyled `LeadsFilter`/`LeadsTable`/
 * `LeadsPagination`/`LeadsViewToggle`/`LeadDrawerContainer`, parameterized by
 * the route's `{tenantId}` (D1) so every fetch targets the S12.7
 * PLATFORM_ADMIN super-user surface `/admin/tenants/{tenantId}/leads*`
 * instead of the implicit `/admin/leads*`. Mirrors `leads/page.tsx`'s
 * server-first architecture exactly (URL searchParams drive filter/
 * pagination/view/drawer state, no client state beyond the drawer itself).
 */
import Link from "next/link";
import { LEAD_STAGES, listLeads } from "@/lib/leads";
import { LeadsFilter } from "@/app/(protected)/leads/leads-filter";
import { LeadsTable } from "@/app/(protected)/leads/leads-table";
import { LeadsPagination } from "@/app/(protected)/leads/leads-pagination";
import { LeadsViewToggle } from "@/app/(protected)/leads/leads-view-toggle";
import { LeadDrawerContainer } from "@/app/(protected)/leads/lead-drawer-container";

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

  function pageHref(page: number, stage: string | undefined, view: string | undefined): string {
    const query = new URLSearchParams();
    if (page > 1) query.set("page", String(page));
    if (stage) query.set("stage", stage);
    if (view === "board") query.set("view", view);
    const qs = query.toString();
    return qs ? `${basePath}?${qs}` : basePath;
  }

  const resolvedSearchParams = await searchParams;
  const rawStage = firstValue(resolvedSearchParams.stage);
  const stage =
    rawStage && (LEAD_STAGES as readonly string[]).includes(rawStage) ? rawStage : undefined;
  const rawPage = Number.parseInt(firstValue(resolvedSearchParams.page) ?? "1", 10);
  const page = Number.isFinite(rawPage) && rawPage >= 1 ? rawPage : 1;
  const view = firstValue(resolvedSearchParams.view) === "board" ? "board" : "table";
  const leadId = firstValue(resolvedSearchParams.lead);
  const tab = firstValue(resolvedSearchParams.tab);

  const currentParams = new URLSearchParams();
  if (page > 1) currentParams.set("page", String(page));
  if (stage) currentParams.set("stage", stage);
  if (view === "board") currentParams.set("view", view);

  const result = await listLeads({ page, stage }, tenantId);

  return (
    <div className="flex flex-1 flex-col gap-4 p-6 lg:p-8">
      <div className="flex flex-wrap items-center gap-3.5">
        <h1 className="text-xl font-bold text-[#191a17]">Leads</h1>
        <LeadsViewToggle view={view} basePath={basePath} currentParams={currentParams} />
        <div className="ml-auto flex items-center gap-2.5">
          <LeadsFilter currentStage={stage} basePath={basePath} />
        </div>
      </div>

      {view === "board" ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 rounded-[14px] border border-dashed border-[#d5d5cb] p-12 text-center">
          <p className="text-sm font-semibold text-[#45463f]">Board view is coming soon</p>
          <p className="max-w-sm text-xs text-[#96978e]">
            Kanban drag-and-drop between stages is a follow-up; see the Leads screen for the same
            scope note.
          </p>
          <Link href={basePath} className="mt-1 text-xs font-semibold text-[#191a17] underline underline-offset-2">
            Switch to Table
          </Link>
        </div>
      ) : result.status === "error" ? (
        <p
          role="alert"
          className="rounded-[14px] border border-[#f6e3df] bg-[#fdf5f3] p-3 text-sm text-[#c2452d]"
        >
          {result.message}
          {result.correlationId ? (
            <span className="block text-xs opacity-80">Correlation ID: {result.correlationId}</span>
          ) : null}
        </p>
      ) : result.items.length === 0 ? (
        <div className="flex flex-col gap-3">
          <p role="status" className="rounded-[14px] border border-[#e7e7e2] bg-[#f7f7f3] p-4 text-sm text-[#45463f]">
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
            <Link href={pageHref(page - 1, stage, view)} className="text-sm underline">
              Previous
            </Link>
          ) : null}
        </div>
      ) : (
        <>
          <LeadsTable
            items={result.items}
            basePath={basePath}
            currentParams={currentParams}
            selectedLeadId={leadId}
          />
          <LeadsPagination
            page={page}
            hasPrevious={result.offset > 0}
            hasNext={result.offset + result.limit < result.total}
            prevHref={pageHref(page - 1, stage, view)}
            nextHref={pageHref(page + 1, stage, view)}
            rangeLabel={`Showing ${result.offset + 1}–${result.offset + result.items.length} of ${result.total}`}
          />
        </>
      )}

      {leadId ? (
        <LeadDrawerContainer leadId={leadId} rawTab={tab} basePath={basePath} tenantId={tenantId} />
      ) : null}
    </div>
  );
}
