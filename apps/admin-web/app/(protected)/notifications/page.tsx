/**
 * Notifications inbox shell (design screen "7a", HANDOFF-SPEC.md §3:
 * "filter pills All/Leads/Mentions/System, unread = #fdfdec + 3px citron
 * bar, per-item action buttons, icon circles tinted by type").
 *
 * SCOPE NOTE (read before touching this file): `services/api/src/api/
 * notifications/admin_routes.py` has NO notifications feed/inbox endpoint.
 * The only real routes are `PUT /admin/notifications/config` (channel
 * config) and `POST /admin/notifications/test-send` (send a test message).
 * There is no `GET /admin/notifications` list, no read/unread state, and no
 * per-item data anywhere in the backend.
 *
 * Per CLAUDE.md §3 "no silent fallbacks" (never serve fake/sample data when
 * real data is unavailable -- fail/omit explicitly), this page renders the
 * full 7a visual language (header, icon-circle treatment, unread striping
 * recipe, per-item action-button styling as documented, not as fabricated
 * rows) around an HONEST EMPTY STATE instead of inventing notification
 * items. No "New qualified lead"/"Call booked"/mention/system rows are
 * hardcoded anywhere below -- the empty state is the truthful rendering of
 * "this backend cannot produce a feed yet".
 *
 * Filter pills (All/Leads/Mentions/System) are still rendered per the design
 * -- they are part of the shell's visual language -- but marked inert
 * (`aria-disabled`, non-interactive, no href/onClick) since there is no data
 * for them to filter. A disabled-looking segmented control would be more
 * confusing than pills that simply don't claim to do anything; instead each
 * pill is followed (visually, via the section) by the explicit empty-state
 * copy so nothing here misrepresents live filtering as functional.
 *
 * A real feed needs its own backend sprint: a notifications table + list
 * endpoint + read/unread state. Flagged as a follow-up, not built here.
 */
import { requireAnyRole } from "@/lib/auth";

const FILTER_PILLS = ["All", "Leads", "Mentions", "System"] as const;

export default async function NotificationsPage() {
  await requireAnyRole("CLIENT_ADMIN", "CLIENT_AGENT", "PLATFORM_ADMIN");

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-1">
        <h1 className="text-[20px] font-bold text-[#191a17]">Notifications</h1>
        <p className="text-[13px] text-[#70716a]">
          Lead activity, mentions, and system events for your workspace.
        </p>
      </div>

      <div className="overflow-hidden rounded-[14px] border border-[#e7e7e2] bg-white">
        {/* Header row -- mirrors 7a's title + count-badge + actions strip.
            No unread count is shown: there is no real unread state to
            count, and a fabricated "0 new" would imply a feed exists. */}
        <div className="flex items-center gap-3 border-b border-[#e7e7e2] px-[22px] py-[18px]">
          <span className="text-[17px] font-bold text-[#191a17]">Inbox</span>
        </div>

        {/* Filter pills -- rendered per 7a's visual language but inert:
            aria-disabled, not focusable as controls, no href/onClick.
            There is no data source for them to filter against. */}
        <div
          className="flex flex-wrap gap-1.5 border-b border-[#f0f0ea] px-[22px] py-3"
          role="group"
          aria-label="Notification filters (not yet available)"
        >
          {FILTER_PILLS.map((pill, index) => (
            <span
              key={pill}
              aria-disabled="true"
              className={
                index === 0
                  ? "rounded-full bg-[#191a17]/40 px-3 py-[5px] text-[11.5px] font-semibold text-white/70"
                  : "rounded-full border border-[#e7e7e2] px-3 py-[5px] text-[11.5px] font-semibold text-[#96978e]"
              }
            >
              {pill}
            </span>
          ))}
        </div>

        {/* Honest empty state -- a real status region (role="status"), not
            decorative text, per ui-ux-pro-max accessibility guidance: it
            must be announced to assistive tech, and must not rely on color
            alone to convey "nothing here". */}
        <div
          role="status"
          className="flex min-h-[360px] flex-col items-center justify-center gap-3 px-[22px] py-16 text-center"
        >
          <div
            aria-hidden="true"
            className="flex h-14 w-14 items-center justify-center rounded-full bg-[#ecece5] text-[22px]"
          >
            🔔
          </div>
          <p className="text-[15px] font-bold text-[#191a17]">No notifications yet</p>
          <p className="max-w-[360px] text-[13px] leading-[1.5] text-[#70716a]">
            This workspace doesn&apos;t have a notifications feed connected yet. Lead
            activity, mentions, and system events will appear here once that&apos;s
            available.
          </p>
        </div>
      </div>
    </div>
  );
}
