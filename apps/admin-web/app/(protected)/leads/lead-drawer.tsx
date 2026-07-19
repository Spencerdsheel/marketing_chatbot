"use client";

/**
 * 4b right-side lead detail drawer (HANDOFF-SPEC.md §1/§2/§3/§4). 440px,
 * shadow `-24px 0 48px rgba(25,26,23,.14)`, tabs Transcript/Details/Activity/
 * Notes with a citron underline on the active tab.
 *
 * State lives in the URL (`?lead=<id>&tab=<tab>`, decision from the task
 * brief) so the drawer is linkable/shareable -- the same pattern
 * `leads-filter.tsx` already uses for the stage filter, just router-driven
 * instead of a `<form method="get">` since this needs client-side Esc/focus
 * handling a plain form navigation can't provide.
 *
 * Data: `page.tsx` fetches the lead detail + activities server-side (this
 * repo's server-first convention) and passes them down as props -- this
 * component only renders what it's given plus owns tab/open/focus state.
 * The Transcript tab has no backend data source at all (no
 * conversation_id link exists on `Lead` yet) -- it renders an honest
 * "not available" state rather than fabricating a transcript
 * (CLAUDE.md §3, no silent fallbacks).
 *
 * Keyboard/focus (mirrors apps/widget/src/ui/ChatWidget.tsx's S14.5 pattern):
 * focus moves into the panel on open, Escape closes, a hand-rolled focus
 * trap keeps Tab/Shift+Tab cycling within the panel, and focus restores to
 * the row/trigger that opened it on close.
 */
import { useActionState, useCallback, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import type {
  LeadActivityItem,
  LeadDetail,
  LeadDetailResult,
  LeadActivitiesResult,
} from "@/lib/leads-presentation";
import { initialsFromName, scoreChipStyle, stageBadgeStyle } from "@/lib/leads-presentation";
import { addLeadNote, type AddNoteState } from "@/app/(protected)/leads/actions";

const TABS = ["transcript", "details", "activity", "notes"] as const;
type Tab = (typeof TABS)[number];

const TAB_LABELS: Record<Tab, string> = {
  transcript: "Transcript",
  details: "Details",
  activity: "Activity",
  notes: "Notes",
};

function formatDateTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function activitySummary(activity: LeadActivityItem): string {
  const payload = activity.payload ?? {};
  switch (activity.type) {
    case "stage_change":
      return `Stage changed: ${String(payload.from_stage ?? "?")} → ${String(payload.to_stage ?? "?")}`;
    case "assignment":
      return payload.agent_id
        ? `Assigned to agent ${String(payload.agent_id)}`
        : "Unassigned";
    case "note":
      return typeof payload.text === "string" ? payload.text : "(note)";
    default:
      return activity.type;
  }
}

const initialNoteState: AddNoteState = { status: "idle" };

interface LeadDrawerProps {
  leadId: string;
  tab: Tab;
  detailResult: LeadDetailResult;
  activitiesResult: LeadActivitiesResult | null;
  /** Base path (`/leads` or `/clients/{tenantId}/leads`) the drawer's URL
   * params are read/written against -- mirrors `leads-filter.tsx`'s
   * `basePath` convention for the S13.7 platform-admin tenant-scoped view. */
  basePath: string;
  tenantId?: string;
}

export function LeadDrawer({
  leadId,
  tab,
  detailResult,
  activitiesResult,
  basePath,
  tenantId,
}: LeadDrawerProps) {
  const router = useRouter();
  const panelRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  const navigate = useCallback(
    (nextLeadId: string | null, nextTab: Tab) => {
      const params = new URLSearchParams();
      if (nextLeadId) {
        params.set("lead", nextLeadId);
        if (nextTab !== "transcript") params.set("tab", nextTab);
      }
      const qs = params.toString();
      router.push(qs ? `${basePath}?${qs}` : basePath, { scroll: false });
    },
    [router, basePath]
  );

  const close = useCallback(() => navigate(null, "transcript"), [navigate]);

  // Focus-in on open + focus-restore on close (mirrors ChatWidget.tsx).
  const triggerRef = useRef<Element | null>(null);
  useEffect(() => {
    triggerRef.current = document.activeElement;
    closeButtonRef.current?.focus();
    return () => {
      if (triggerRef.current instanceof HTMLElement) {
        triggerRef.current.focus();
      }
    };
    // Mount/unmount only -- this effect intentionally does not depend on
    // leadId so switching leads while open doesn't re-trigger focus jumps.
  }, []);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
        return;
      }
      if (event.key !== "Tab") return;

      const panel = panelRef.current;
      if (!panel) return;
      const focusable = panel.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;

      if (event.shiftKey) {
        if (active === first || !panel.contains(active)) {
          event.preventDefault();
          last.focus();
        }
      } else if (active === last || !panel.contains(active)) {
        event.preventDefault();
        first.focus();
      }
    },
    [close]
  );

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="lead-drawer-title"
      ref={panelRef}
      onKeyDown={handleKeyDown}
      className="fixed top-0 right-0 bottom-0 z-50 flex w-full max-w-[440px] flex-col bg-white"
      style={{ boxShadow: "-24px 0 48px rgba(25,26,23,.14)", borderLeft: "1px solid #e7e7e2" }}
    >
      {detailResult.status === "error" ? (
        <DrawerErrorState message={detailResult.message} correlationId={detailResult.correlationId} onClose={close} closeButtonRef={closeButtonRef} />
      ) : (
        <DrawerBody
          lead={detailResult.lead}
          tab={tab}
          activitiesResult={activitiesResult}
          onClose={close}
          onTabChange={(nextTab) => navigate(leadId, nextTab)}
          closeButtonRef={closeButtonRef}
          tenantId={tenantId}
          leadId={leadId}
          basePath={basePath}
        />
      )}
    </div>
  );
}

function DrawerErrorState({
  message,
  correlationId,
  onClose,
  closeButtonRef,
}: {
  message: string;
  correlationId: string;
  onClose: () => void;
  closeButtonRef: React.RefObject<HTMLButtonElement | null>;
}) {
  return (
    <div className="flex flex-1 flex-col gap-4 p-6">
      <div className="flex items-center justify-between">
        <span id="lead-drawer-title" className="text-base font-bold text-[#191a17]">
          Lead unavailable
        </span>
        <CloseButton onClose={onClose} closeButtonRef={closeButtonRef} />
      </div>
      <p role="alert" className="rounded-lg border border-[#f6e3df] bg-[#fdf5f3] p-3 text-sm text-[#c2452d]">
        {message}
        {correlationId ? <span className="mt-1 block text-xs opacity-80">Correlation ID: {correlationId}</span> : null}
      </p>
    </div>
  );
}

function CloseButton({
  onClose,
  closeButtonRef,
}: {
  onClose: () => void;
  closeButtonRef: React.RefObject<HTMLButtonElement | null>;
}) {
  return (
    <button
      ref={closeButtonRef}
      type="button"
      onClick={onClose}
      aria-label="Close lead detail"
      className="grid size-11 shrink-0 place-items-center rounded-lg text-[#a8a99f] transition-colors hover:bg-[#f0f0ea] hover:text-[#191a17] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#191a17]"
    >
      <span aria-hidden className="text-sm">
        ✕
      </span>
    </button>
  );
}

function DrawerBody({
  lead,
  tab,
  activitiesResult,
  onClose,
  onTabChange,
  closeButtonRef,
  tenantId,
  leadId,
  basePath,
}: {
  lead: LeadDetail;
  tab: Tab;
  activitiesResult: LeadActivitiesResult | null;
  onClose: () => void;
  onTabChange: (tab: Tab) => void;
  closeButtonRef: React.RefObject<HTMLButtonElement | null>;
  tenantId?: string;
  leadId: string;
  basePath: string;
}) {
  const stageBadge = stageBadgeStyle(lead.stage);
  const scoreBadge = lead.qualificationScore !== null ? scoreChipStyle(lead.qualificationScore, lead.stage) : null;
  const noteCount =
    activitiesResult?.status === "ok"
      ? activitiesResult.items.filter((activity) => activity.type === "note").length
      : 0;

  return (
    <>
      <div className="flex flex-col gap-3.5 border-b border-[#e7e7e2] p-5">
        <div className="flex items-center gap-3">
          <div className="grid size-11 shrink-0 place-items-center rounded-full bg-[#191a17] text-sm font-bold text-[#e4f222]">
            {initialsFromName(lead.name)}
          </div>
          <div className="min-w-0 flex-1">
            <p id="lead-drawer-title" className="truncate text-base font-bold text-[#191a17]">
              {lead.name}
            </p>
            <p className="truncate text-xs text-[#70716a]">
              {lead.email}
              {lead.phone ? ` · ${lead.phone}` : ""}
            </p>
          </div>
          <CloseButton onClose={onClose} closeButtonRef={closeButtonRef} />
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge label={stageBadge.label} bg={stageBadge.bg} fg={stageBadge.fg} />
          {scoreBadge ? <Badge label={`SCORE ${scoreBadge.label}`} bg={scoreBadge.bg === "transparent" ? "#f0f0ea" : scoreBadge.bg} fg={scoreBadge.fg} /> : null}
          <span className="rounded-full border border-[#e7e7e2] px-2.5 py-1 text-[11px] font-semibold text-[#5a5b54]">
            {lead.source}
          </span>
        </div>
      </div>

      <div className="flex border-b border-[#e7e7e2] text-[12.5px] font-semibold" role="tablist" aria-label="Lead detail sections">
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            id={`lead-tab-${t}`}
            aria-selected={tab === t}
            aria-controls={`lead-tabpanel-${t}`}
            onClick={() => onTabChange(t)}
            className="min-h-11 px-4 py-2.5 transition-colors focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[#191a17]"
            style={{
              color: tab === t ? "#191a17" : "#96978e",
              borderBottom: tab === t ? "2px solid #e4f222" : "2px solid transparent",
            }}
          >
            {TAB_LABELS[t]}
            {t === "notes" && noteCount > 0 ? (
              <span className="ml-1.5 rounded-full bg-[#ecece5] px-1.5 py-0.5 text-[10px] font-bold text-[#5a5b54]">
                {noteCount}
              </span>
            ) : null}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto">
        {tab === "transcript" ? (
          <TranscriptTab />
        ) : tab === "details" ? (
          <DetailsTab lead={lead} />
        ) : tab === "activity" ? (
          <ActivityTab activitiesResult={activitiesResult} />
        ) : (
          <NotesTab
            activitiesResult={activitiesResult}
            leadId={leadId}
            tenantId={tenantId}
            basePath={basePath}
          />
        )}
      </div>
    </>
  );
}

function Badge({ label, bg, fg }: { label: string; bg: string; fg: string }) {
  return (
    <span
      className="rounded-full px-2.5 py-1 text-[11px] font-bold"
      style={{ background: bg, color: fg }}
    >
      {label}
    </span>
  );
}

/**
 * No backend endpoint links a lead to a conversation transcript (`Lead` has
 * no `conversation_id` field, per `services/api/src/api/leads/repository.py`)
 * -- this is an honest "not available yet" state, not a fabricated
 * transcript (CLAUDE.md §3, no silent fallbacks).
 */
function TranscriptTab() {
  return (
    <div
      id="lead-tabpanel-transcript"
      role="tabpanel"
      aria-labelledby="lead-tab-transcript"
      className="flex flex-1 flex-col items-center justify-center gap-2 p-8 text-center"
    >
      <p className="text-sm font-semibold text-[#45463f]">Transcript not available</p>
      <p className="max-w-[280px] text-xs text-[#96978e]">
        This lead isn&apos;t linked to a conversation record yet, so there&apos;s no transcript to show here.
      </p>
    </div>
  );
}

function DetailsTab({ lead }: { lead: LeadDetail }) {
  const rows: Array<[string, string]> = [
    ["Email", lead.email],
    ["Phone", lead.phone ?? "—"],
    ["Status", lead.status],
    ["Stage", lead.stage],
    ["Score", lead.qualificationScore !== null ? String(lead.qualificationScore) : "—"],
    ["Source", lead.source],
    ["Assigned agent", lead.assignedAgentId ?? "— Unassigned"],
  ];
  return (
    <dl id="lead-tabpanel-details" role="tabpanel" aria-labelledby="lead-tab-details" className="flex flex-col gap-3 p-5">
      {rows.map(([label, value]) => (
        <div key={label} className="flex items-center justify-between gap-4 border-b border-[#f0f0ea] pb-3 text-[13px] last:border-b-0">
          <dt className="text-[#70716a]">{label}</dt>
          <dd className="truncate font-medium text-[#191a17]">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function ActivityTab({ activitiesResult }: { activitiesResult: LeadActivitiesResult | null }) {
  if (activitiesResult === null) {
    return (
      <p id="lead-tabpanel-activity" role="tabpanel" aria-labelledby="lead-tab-activity" className="p-5 text-sm text-[#96978e]">
        Loading activity…
      </p>
    );
  }
  if (activitiesResult.status === "error") {
    return (
      <p role="alert" id="lead-tabpanel-activity" className="m-5 rounded-lg border border-[#f6e3df] bg-[#fdf5f3] p-3 text-sm text-[#c2452d]">
        {activitiesResult.message}
      </p>
    );
  }
  if (activitiesResult.items.length === 0) {
    return (
      <p id="lead-tabpanel-activity" role="tabpanel" aria-labelledby="lead-tab-activity" className="p-5 text-sm text-[#96978e]">
        No activity recorded yet.
      </p>
    );
  }
  return (
    <ul id="lead-tabpanel-activity" role="tabpanel" aria-labelledby="lead-tab-activity" className="flex flex-col gap-3 p-5">
      {activitiesResult.items.map((activity) => (
        <li key={activity.activityId} className="flex flex-col gap-1 border-b border-[#f0f0ea] pb-3 text-[12.5px] last:border-b-0">
          <span className="text-[#191a17]">{activitySummary(activity)}</span>
          <span className="text-[11px] text-[#96978e]">
            {formatDateTime(activity.createdAt)}
            {activity.actor ? ` · ${activity.actor}` : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}

function NotesTab({
  activitiesResult,
  leadId,
  tenantId,
  basePath,
}: {
  activitiesResult: LeadActivitiesResult | null;
  leadId: string;
  tenantId?: string;
  basePath: string;
}) {
  const boundAction = addLeadNote.bind(null, tenantId, leadId, basePath);
  const [state, formAction, pending] = useActionState(boundAction, initialNoteState);
  const notes =
    activitiesResult?.status === "ok"
      ? activitiesResult.items.filter((activity) => activity.type === "note")
      : [];

  return (
    <div id="lead-tabpanel-notes" role="tabpanel" aria-labelledby="lead-tab-notes" className="flex flex-1 flex-col gap-4 p-5">
      <form action={formAction} className="flex flex-col gap-2">
        <label htmlFor="note-text" className="text-xs font-semibold text-[#5a5b54]">
          Add a note
        </label>
        <textarea
          id="note-text"
          name="text"
          rows={3}
          maxLength={4000}
          className="rounded-lg border border-[#e7e7e2] p-2.5 text-[13px] text-[#191a17] outline-none focus-visible:border-[#191a17]"
          placeholder="Write a note about this lead…"
        />
        {state.status === "error" ? (
          <p role="alert" className="text-xs text-[#c2452d]">
            {state.message}
          </p>
        ) : null}
        <button
          type="submit"
          disabled={pending}
          className="min-h-11 self-start rounded-lg bg-[#191a17] px-4 text-[12.5px] font-bold text-[#e4f222] transition-opacity disabled:opacity-50"
        >
          {pending ? "Saving…" : "Save note"}
        </button>
      </form>

      {activitiesResult?.status === "error" ? (
        <p role="alert" className="rounded-lg border border-[#f6e3df] bg-[#fdf5f3] p-3 text-sm text-[#c2452d]">
          {activitiesResult.message}
        </p>
      ) : notes.length === 0 ? (
        <p className="text-sm text-[#96978e]">No notes yet.</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {notes.map((note) => (
            <li key={note.activityId} className="flex flex-col gap-1 border-b border-[#f0f0ea] pb-3 text-[12.5px] last:border-b-0">
              <span className="text-[#191a17]">{typeof note.payload?.text === "string" ? note.payload.text : ""}</span>
              <span className="text-[11px] text-[#96978e]">
                {formatDateTime(note.createdAt)}
                {note.actor ? ` · ${note.actor}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export type { Tab };
export { TABS };
