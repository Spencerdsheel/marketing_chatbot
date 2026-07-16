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

export function LeadsFilter({ currentStage }: { currentStage: string | undefined }) {
  return (
    <form
      action="/leads"
      method="get"
      className="flex flex-wrap items-end gap-3"
    >
      <div className="flex flex-col gap-1">
        <label htmlFor="stage" className="text-xs font-medium text-muted-foreground">
          Stage
        </label>
        <select
          id="stage"
          name="stage"
          defaultValue={currentStage ?? ""}
          className="h-8 rounded-lg border border-input bg-transparent px-2.5 py-1 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
        >
          <option value="">All stages</option>
          {LEAD_STAGES.map((stage) => (
            <option key={stage} value={stage}>
              {STAGE_LABELS[stage]}
            </option>
          ))}
        </select>
      </div>
      <button
        type="submit"
        className="h-8 rounded-lg border border-transparent bg-primary px-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/80"
      >
        Filter
      </button>
      {currentStage ? (
        <Link href="/leads" className="text-sm text-muted-foreground hover:underline">
          Clear filter
        </Link>
      ) : null}
    </form>
  );
}
