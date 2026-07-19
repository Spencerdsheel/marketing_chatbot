/**
 * Status filter pills for the 4a conversation list (HANDOFF-SPEC.md §3:
 * "filter pills"). The mock (`id="4a"`) shows four pills -- All / Live /
 * Lead captured / Ended -- but the real backend `status` query param only
 * accepts `active`/`ended` (admin_routes.py `_VALID_STATUSES`) and there is
 * no lead-linkage field to filter on. Per the mandated scope decision, the
 * pill *values* are the real ones (All / Active / Ended) while keeping the
 * mock's pill visual style (99px radius, ink-filled active pill, bordered
 * inactive pills).
 *
 * Plain `<Link>`s (not client-side `onClick` + router.push) so this stays
 * server-renderable/no-JS-navigable like `leads-filter.tsx`'s form -- no
 * "use client" needed here.
 */
import Link from "next/link";
import type { ConversationStatus } from "@/lib/conversations";

const STATUS_LABELS: Record<ConversationStatus, string> = {
  active: "Active",
  ended: "Ended",
};

function pillHref(basePath: string, status: ConversationStatus | undefined): string {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  const qs = params.toString();
  return qs ? `${basePath}?${qs}` : basePath;
}

export function ConversationsFilter({
  currentStatus,
  basePath,
  statuses,
}: {
  currentStatus: ConversationStatus | undefined;
  basePath: string;
  statuses: readonly ConversationStatus[];
}) {
  const pillClass = (active: boolean) =>
    active
      ? "inline-flex min-h-9 items-center rounded-full bg-[#191a17] px-3 text-[11.5px] font-semibold text-white"
      : "inline-flex min-h-9 items-center rounded-full border border-[#e7e7e2] px-3 text-[11.5px] font-semibold text-[#5a5b54] hover:bg-[#f7f7f3]";

  return (
    <div role="group" aria-label="Filter conversations by status" className="flex flex-wrap gap-1.5">
      <Link
        href={pillHref(basePath, undefined)}
        aria-current={currentStatus === undefined ? "true" : undefined}
        className={pillClass(currentStatus === undefined)}
      >
        All
      </Link>
      {statuses.map((status) => (
        <Link
          key={status}
          href={pillHref(basePath, status)}
          aria-current={currentStatus === status ? "true" : undefined}
          className={pillClass(currentStatus === status)}
        >
          {STATUS_LABELS[status]}
        </Link>
      ))}
    </div>
  );
}
