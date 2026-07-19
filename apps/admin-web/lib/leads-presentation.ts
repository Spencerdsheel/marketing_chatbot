/**
 * Client-safe presentation layer for leads (4b). Pure types + pure lookup
 * functions only -- no `server-only` import, no data fetching -- so Client
 * Components (`lead-drawer.tsx`) can import them directly without pulling
 * the server-only `lib/leads.ts` (and its `adminApiFetch`/`server-only`
 * import) into the client bundle.
 *
 * `lib/leads.ts` re-exports everything from this module so existing server
 * consumers (`leads-table.tsx`, `lib/dashboard.ts`, tests importing from
 * `@/lib/leads`) keep working unchanged -- this file is the single source of
 * truth for these types/functions, `lib/leads.ts` just forwards them.
 */

/** Same leak-free shape as `LeadListItem` minus `createdAt` (mirrors
 * `LeadDetailResponse`, admin_routes.py:106-117). */
export interface LeadDetail {
  leadId: string;
  name: string;
  email: string;
  phone: string | null;
  status: string;
  stage: string;
  qualificationScore: number | null;
  assignedAgentId: string | null;
  source: string;
}

export type LeadDetailResult =
  | { status: "ok"; lead: LeadDetail }
  | { status: "error"; message: string; correlationId: string };

/** A single timeline entry -- mirrors `LeadActivityResponse`
 * (admin_routes.py:84-92) exactly, no `tenant_id`. `type` is one of
 * `stage_change` | `note` | `assignment` (the three activity types the
 * backend ever writes, per `admin_routes.py`'s `add_activity` call sites). */
export interface LeadActivityItem {
  activityId: string;
  leadId: string;
  type: string;
  payload: Record<string, unknown> | null;
  actor: string | null;
  createdAt: string;
}

export type LeadActivitiesResult =
  | { status: "ok"; items: LeadActivityItem[] }
  | { status: "error"; message: string; correlationId: string };

// ---------------------------------------------------------------------------
// 4b design tokens -- pure lookup helpers (HANDOFF-SPEC.md §2 Badges).
// Kept as pure functions (unit-testable, no JSX) per this repo's convention
// of testing pure logic rather than rendering.
// ---------------------------------------------------------------------------

export interface BadgeStyle {
  label: string;
  bg: string;
  fg: string;
}

const STAGE_BADGES: Record<string, BadgeStyle> = {
  captured: { label: "CAPTURED", bg: "#ecece5", fg: "#5a5b54" },
  qualified: { label: "QUALIFIED", bg: "#eef7a8", fg: "#191a17" },
  contacted: { label: "CONTACTED", bg: "#dcefdc", fg: "#1f6a2f" },
  converted: { label: "CONVERTED", bg: "#191a17", fg: "#e4f222" },
  disqualified: { label: "DISQUALIFIED", bg: "#f6e3df", fg: "#c2452d" },
};

/** Stage -> badge color/label (HANDOFF-SPEC.md §2 Badges). Unknown stages
 * fall back to a neutral muted style rather than throwing -- the backend's
 * `_VALID_STAGES` set is the real gate, this is presentation only. */
export function stageBadgeStyle(stage: string): BadgeStyle {
  return STAGE_BADGES[stage] ?? { label: stage.toUpperCase(), bg: "#ecece5", fg: "#5a5b54" };
}

/** Score chip color (HANDOFF-SPEC.md §2: "Score chip: #eef7a8 bg (≥60),
 * #dcefdc/#1f6a2f (converted), plain muted text below threshold"). `null`
 * (no score yet) renders as the muted em-dash, handled by the caller. */
export function scoreChipStyle(score: number, stage: string): BadgeStyle {
  if (stage === "converted") {
    return { label: String(score), bg: "#dcefdc", fg: "#1f6a2f" };
  }
  if (score >= 60) {
    return { label: String(score), bg: "#eef7a8", fg: "#191a17" };
  }
  return { label: String(score), bg: "transparent", fg: "#96978e" };
}

/** Two-letter initials for the assigned-agent avatar chip, e.g. "Sara R."
 * -> "SR". Falls back to "?" for an empty/whitespace-only name so the avatar
 * never renders blank. */
export function initialsFromName(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}
