/**
 * 4b Board/Table segmented toggle (HANDOFF-SPEC.md §4: "Board/Table is a
 * segmented toggle, state in URL"). Scope decision (see task report): only
 * the Table view is implemented this pass. Board (kanban with drag-and-drop
 * stage transitions) is a materially larger feature -- a full drag/drop
 * surface writing `PATCH /admin/leads/{id}` against production lead data --
 * and out of scope for a UI-only restyle. The toggle affordance itself is
 * still built per spec and wired to `?view=`, but selecting "Board" shows an
 * honest "coming soon" panel rather than either a half-built drag surface or
 * silently doing nothing (CLAUDE.md §3, no silent fallbacks applies to UI
 * affordances too -- a toggle that appears to do something must actually
 * reflect a real, if limited, state change).
 */
import Link from "next/link";

export function LeadsViewToggle({
  view,
  basePath,
  currentParams,
}: {
  view: "table" | "board";
  basePath: string;
  currentParams: URLSearchParams;
}) {
  function hrefFor(nextView: "table" | "board"): string {
    const params = new URLSearchParams(currentParams);
    params.delete("lead");
    params.delete("tab");
    if (nextView === "table") {
      params.delete("view");
    } else {
      params.set("view", nextView);
    }
    const qs = params.toString();
    return qs ? `${basePath}?${qs}` : basePath;
  }

  return (
    <div className="flex overflow-hidden rounded-lg border border-[#e7e7e2] text-xs font-semibold" role="group" aria-label="Leads view">
      <Link
        href={hrefFor("board")}
        scroll={false}
        aria-current={view === "board" ? "page" : undefined}
        className="min-h-9 px-3.5 py-1.5"
        style={view === "board" ? { background: "#191a17", color: "#fff" } : { color: "#5a5b54" }}
      >
        Board
      </Link>
      <Link
        href={hrefFor("table")}
        scroll={false}
        aria-current={view === "table" ? "page" : undefined}
        className="min-h-9 px-3.5 py-1.5"
        style={view === "table" ? { background: "#191a17", color: "#fff" } : { color: "#5a5b54" }}
      >
        Table
      </Link>
    </div>
  );
}
