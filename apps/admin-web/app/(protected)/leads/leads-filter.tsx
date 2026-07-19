/**
 * Stage filter (S13.4 decision 5). A plain GET `<form>` with a native
 * `<select name="stage">` -- no client JS, no `select` primitive dependency
 * (decision 7). Submitting navigates to `/leads?stage=...`, which resets
 * pagination to page 1 (the `page` param is simply omitted from this form,
 * so a fresh submit always lands on page 1). Server component -- no
 * `"use client"` needed.
 */
import Link from "next/link";
import { LEAD_STAGES } from "@/lib/leads";

const STAGE_LABELS: Record<(typeof LEAD_STAGES)[number], string> = {
  captured: "Captured",
  qualified: "Qualified",
  contacted: "Contacted",
  converted: "Converted",
  disqualified: "Disqualified",
};

/**
 * `basePath` (S13.7): the per-client leads screen passes
 * `/clients/{tenantId}/leads` so the filter form and "Clear filter" link
 * stay on that same tenant-scoped route instead of the implicit `/leads`.
 * Defaults to `/leads`, preserving the existing CLIENT_ADMIN/AGENT behavior.
 */
export function LeadsFilter({
  currentStage,
  basePath = "/leads",
}: {
  currentStage: string | undefined;
  basePath?: string;
}) {
  return (
    <form
      action={basePath}
      method="get"
      className="flex flex-wrap items-center gap-2.5"
    >
      <label htmlFor="stage" className="sr-only">
        Stage
      </label>
      <select
        id="stage"
        name="stage"
        defaultValue={currentStage ?? ""}
        className="min-h-9 rounded-[9px] border border-[#e7e7e2] bg-white px-3 text-[12.5px] text-[#45463f] outline-none focus-visible:border-[#191a17]"
      >
        <option value="">All stages</option>
        {LEAD_STAGES.map((stage) => (
          <option key={stage} value={stage}>
            {STAGE_LABELS[stage]}
          </option>
        ))}
      </select>
      <button
        type="submit"
        className="min-h-9 rounded-[9px] border border-[#e7e7e2] bg-white px-3.5 text-[12.5px] font-semibold text-[#45463f] hover:bg-[#f7f7f3]"
      >
        Filter
      </button>
      {currentStage ? (
        <Link href={basePath} className="text-[12.5px] text-[#70716a] underline underline-offset-2">
          Clear filter
        </Link>
      ) : null}
    </form>
  );
}
