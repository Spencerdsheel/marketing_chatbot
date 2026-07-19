/**
 * 4b leads table (HANDOFF-SPEC.md §2 Tables + §2 Badges). Restyled from the
 * original shadcn `<Table>` to the exact design recipe: header row #f7f7f3
 * 11.5px/600 uppercase muted, rows 13px with `border-faint` dividers, stage
 * badges + score chip per the color table, initials avatar for the assigned
 * agent. Still a pure presentation component fed rows the server component
 * already fetched -- columns are the same leak-free `LeadListItem` fields,
 * just restyled (Name, Email, Stage, Status, Score, Assigned, Created).
 *
 * Each row is a link to `{basePath}?...&lead={id}` (opens the 4b drawer,
 * HANDOFF-SPEC.md §4 "Drawer opens from table row or 'View lead'") --
 * `<Link>`, not a client onClick, so it's keyboard/middle-click/right-click
 * navigable like any other link in this server-first codebase, and works
 * with JS disabled (progressive enhancement).
 */
import Link from "next/link";
import type { LeadListItem } from "@/lib/leads";
import { initialsFromName, scoreChipStyle, stageBadgeStyle } from "@/lib/leads";

const MUTED = <span style={{ color: "#96978e" }}>—</span>;

function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function leadHref(basePath: string, currentParams: URLSearchParams, leadId: string): string {
  const params = new URLSearchParams(currentParams);
  params.set("lead", leadId);
  params.delete("tab");
  return `${basePath}?${params.toString()}`;
}

const HEADERS = ["Name", "Email", "Stage", "Status", "Score", "Assigned", "Created"];

export function LeadsTable({
  items,
  basePath,
  currentParams,
  selectedLeadId,
}: {
  items: LeadListItem[];
  /** Base list route (`/leads` or `/clients/{tenantId}/leads`) used to build
   * each row's `?lead=` link -- mirrors `leads-filter.tsx`'s `basePath`. */
  basePath?: string;
  /** Existing query params (stage/page/view) to preserve when adding `lead=`
   * to a row's href, so opening the drawer doesn't drop the current filter. */
  currentParams?: URLSearchParams;
  /** The currently open lead (from `?lead=`), highlighted per HANDOFF-SPEC.md
   * §2 "highlighted row #fdfdec". */
  selectedLeadId?: string;
}) {
  const resolvedBasePath = basePath ?? "/leads";
  const resolvedParams = currentParams ?? new URLSearchParams();

  return (
    <div className="overflow-hidden rounded-[14px] border border-[#e7e7e2] text-[13px]">
      <table className="w-full border-collapse">
        <thead>
          <tr className="border-b border-[#e7e7e2] bg-[#f7f7f3]">
            {HEADERS.map((header) => (
              <th
                key={header}
                scope="col"
                className="px-3.5 py-2.5 text-left text-[11.5px] font-semibold tracking-[0.02em] text-[#70716a] uppercase"
              >
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((lead) => {
            const stageBadge = stageBadgeStyle(lead.stage);
            const scoreBadge =
              lead.qualificationScore !== null ? scoreChipStyle(lead.qualificationScore, lead.stage) : null;
            const highlighted = lead.leadId === selectedLeadId;
            return (
              <tr
                key={lead.leadId}
                className="border-b border-[#f0f0ea] last:border-b-0 hover:bg-[#f7f7f3]"
                style={highlighted ? { background: "#fdfdec" } : undefined}
              >
                <td className="px-0 py-0">
                  <Link
                    href={leadHref(resolvedBasePath, resolvedParams, lead.leadId)}
                    scroll={false}
                    className="block min-h-11 px-3.5 py-3 font-bold text-[#191a17] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[#191a17]"
                  >
                    {lead.name}
                  </Link>
                </td>
                <td className="px-3.5 py-3 text-[#45463f]">{lead.email}</td>
                <td className="px-3.5 py-3">
                  <span
                    className="rounded-full px-2.5 py-[3px] text-[10.5px] font-bold"
                    style={{ background: stageBadge.bg, color: stageBadge.fg }}
                  >
                    {stageBadge.label}
                  </span>
                </td>
                <td className="px-3.5 py-3 text-[#45463f]">{lead.status}</td>
                <td className="px-3.5 py-3">
                  {scoreBadge ? (
                    <span
                      className="rounded-md px-1.5 py-0.5 font-bold"
                      style={{ background: scoreBadge.bg, color: scoreBadge.fg }}
                    >
                      {scoreBadge.label}
                    </span>
                  ) : (
                    MUTED
                  )}
                </td>
                <td className="px-3.5 py-3">
                  {lead.assignedAgentId ? (
                    <span className="flex items-center gap-1.5 text-[#45463f]">
                      <span className="grid size-5 shrink-0 place-items-center rounded-full bg-[#dcdcd2] text-[8.5px] font-bold text-[#5a5b54]">
                        {initialsFromName(lead.assignedAgentId)}
                      </span>
                      {lead.assignedAgentId}
                    </span>
                  ) : (
                    <span style={{ color: "#96978e" }}>— Assign</span>
                  )}
                </td>
                <td className="px-3.5 py-3 text-[#70716a]">{formatDate(lead.createdAt)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
