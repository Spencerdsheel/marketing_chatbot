/**
 * Team members screen (7b), CLIENT_ADMIN-only -- gated by `requireRole`
 * (matches `tenants/new/page.tsx`'s PLATFORM_ADMIN gate). Restyled to 7b's
 * visual language (HANDOFF-SPEC.md §1/§2/§3 "7b"), wired to the three real
 * `/admin/users` endpoints only.
 *
 * 7b elements deliberately omitted or stubbed (locked scope decision):
 *  - Pending-invite banner: OMITTED. There is no invite/token/pending-status
 *    concept anywhere in `users_routes.py` -- `POST /admin/users` creates a
 *    user immediately. Rendering an always-empty invite banner would be
 *    dead UI, so it is dropped rather than faked.
 *  - Open-lead-load column: OMITTED. Confirmed by reading
 *    `services/api/src/api/leads/admin_routes.py` in full -- leads carry an
 *    `assigned_agent_id` but there is no per-agent aggregation/count
 *    endpoint. Fabricating a number here would violate "no silent
 *    fallbacks" (CLAUDE.md §3).
 *  - Auto-assignment toggle: STUBBED, visibly disabled. The card is kept
 *    (7b's visual rhythm) but the toggle renders in a permanently-off,
 *    non-interactive state with a "Not available yet" label -- never a
 *    toggle that silently no-ops when clicked.
 */
import { requireRole } from "@/lib/auth";
import { listMembers } from "@/lib/members";
import { MembersTable } from "@/app/(protected)/members/members-table";
import { CreateMemberDialog } from "@/app/(protected)/members/create-member-dialog";

export default async function MembersPage() {
  await requireRole("CLIENT_ADMIN");

  const result = await listMembers();

  return (
    <div className="flex flex-1 flex-col gap-[18px] p-[22px] md:p-[28px]">
      <div className="flex items-center gap-[14px]">
        <div>
          <h1 className="text-[20px] font-bold text-[#191a17]">Team members</h1>
          <p className="mt-[2px] text-[12.5px] text-[#70716a]">
            {result.status === "ok"
              ? `${result.items.length} member${result.items.length === 1 ? "" : "s"}`
              : "Team members"}
          </p>
        </div>
        <div className="ml-auto">
          <CreateMemberDialog />
        </div>
      </div>

      {result.status === "error" ? (
        <div
          role="alert"
          className="rounded-xl border border-[#f0e2bd] bg-[#fff9ec] px-4 py-3 text-[13px] text-[#6a4e00]"
        >
          {result.message}
          {result.correlationId ? (
            <span className="block text-[11px] text-[#6a4e00]/80">
              Correlation ID: {result.correlationId}
            </span>
          ) : null}
        </div>
      ) : (
        <MembersTable members={result.items} />
      )}

      <div className="flex flex-col gap-3 rounded-[14px] border border-[#e7e7e2] p-[18px]">
        <span className="text-[13.5px] font-bold text-[#191a17]">Auto-assignment</span>
        <div className="flex items-center gap-3">
          <span
            aria-hidden="true"
            className="relative h-5 w-9 flex-none rounded-full bg-[#d5d5cb] opacity-60"
          >
            <span className="absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white" />
          </span>
          <div>
            <div className="text-[13px] font-semibold text-[#191a17]">
              Round-robin new qualified leads
            </div>
            <div className="text-[11.5px] text-[#70716a]">
              Not available yet — automatic lead distribution isn&apos;t configurable from this
              console. Assign leads manually from the Leads console.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
