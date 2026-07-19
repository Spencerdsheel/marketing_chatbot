/**
 * Lead review console (S13.4), restyled to HANDOFF-SPEC.md's "4b" screen:
 * segmented Board/Table toggle, restyled table + badges, bordered pagination
 * chips, and a 440px right-side lead detail drawer (new this pass). Still
 * gated by `requireAnyRole` (decision 2), still an `async` server component
 * that reads all state (filter/pagination/view/drawer) from the URL
 * `searchParams` and fetches once per navigation -- no client state beyond
 * the drawer's own tab/focus handling (`lead-drawer.tsx`).
 *
 * `?lead=<id>` opens the drawer (fetched by `LeadDrawerContainer`); `?tab=`
 * selects its active tab; `?view=board` shows the Board-view placeholder
 * (see `leads-view-toggle.tsx` for the scope decision on why Board isn't a
 * full kanban this pass); `?stage=`/`?page=` are unchanged from S13.4.
 */
import Link from "next/link";
import { requireAnyRole } from "@/lib/auth";
import { LEAD_STAGES, listLeads } from "@/lib/leads";
import { LeadsFilter } from "@/app/(protected)/leads/leads-filter";
import { LeadsTable } from "@/app/(protected)/leads/leads-table";
import { LeadsPagination } from "@/app/(protected)/leads/leads-pagination";
import { LeadsViewToggle } from "@/app/(protected)/leads/leads-view-toggle";
import { LeadDrawerContainer } from "@/app/(protected)/leads/lead-drawer-container";

interface LeadsPageProps {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

function firstValue(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function pageHref(page: number, stage: string | undefined, view: string | undefined): string {
  const query = new URLSearchParams();
  if (page > 1) query.set("page", String(page));
  if (stage) query.set("stage", stage);
  if (view === "board") query.set("view", view);
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
  const view = firstValue(params.view) === "board" ? "board" : "table";
  const leadId = firstValue(params.lead);
  const tab = firstValue(params.tab);

  const currentParams = new URLSearchParams();
  if (page > 1) currentParams.set("page", String(page));
  if (stage) currentParams.set("stage", stage);
  if (view === "board") currentParams.set("view", view);

  const result = await listLeads({ page, stage });

  return (
    <div className="flex flex-1 flex-col gap-4 p-6 lg:p-8">
      <div className="flex flex-wrap items-center gap-3.5">
        <h1 className="text-xl font-bold text-[#191a17]">Leads</h1>
        <LeadsViewToggle view={view} basePath="/leads" currentParams={currentParams} />
        <div className="ml-auto flex items-center gap-2.5">
          <LeadsFilter currentStage={stage} />
          <span
            title="CSV export runs server-side against the authenticated session; wiring a browser-safe download route is out of scope for this UI-only pass."
            aria-disabled="true"
            className="min-h-9 cursor-not-allowed rounded-[9px] bg-[#191a17]/50 px-3.5 py-2 text-[12.5px] font-semibold whitespace-nowrap text-white/80"
          >
            ↧ Export CSV
          </span>
        </div>
      </div>

      {view === "board" ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 rounded-[14px] border border-dashed border-[#d5d5cb] p-12 text-center">
          <p className="text-sm font-semibold text-[#45463f]">Board view is coming soon</p>
          <p className="max-w-sm text-xs text-[#96978e]">
            Kanban drag-and-drop between stages needs its own careful pass against live lead data
            rather than a half-built surface bolted onto this restyle. The dashboard&apos;s pipeline
            columns are the closest existing reference for that follow-up.
          </p>
          <Link href="/leads" className="mt-1 text-xs font-semibold text-[#191a17] underline underline-offset-2">
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
                <Link href="/leads" className="underline">
                  Clear filter
                </Link>
              </>
            ) : result.total === 0 ? (
              "No leads yet -- leads captured by your chatbot will appear here."
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
            basePath="/leads"
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
        <LeadDrawerContainer leadId={leadId} rawTab={tab} basePath="/leads" />
      ) : null}
    </div>
  );
}
