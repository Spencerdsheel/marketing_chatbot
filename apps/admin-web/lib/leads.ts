/**
 * Server-only data layer for the lead review console (S13.4). Builds the
 * `GET /admin/leads` query string, calls `adminApiFetch`, and maps the
 * response (or any error) into a discriminated `LeadsResult` the page
 * renders directly -- no silent fallbacks (CLAUDE.md §3): a backend error
 * always becomes a visible, honest state, never a blank/faked table.
 *
 * Constants below are sourced verbatim from the real backend, not invented:
 *  - `LEAD_STAGES` mirrors `STAGE_ORDER ∪ TERMINAL_STAGES`
 *    (services/api/src/api/leads/pipeline.py:38-41).
 *  - `LEAD_STATUSES` mirrors `_STATUS_BY_STAGE.values()` (pipeline.py:44-50).
 *  - `LEADS_PAGE_SIZE` is a UI choice (S13.4 decision 3, Q1 default 25),
 *    well within the backend's `[1,200]` clamp (admin_routes.py:236).
 */
import "server-only";

import { adminApiFetch, AdminApiError } from "@/lib/api";
import type {
  LeadDetail,
  LeadDetailResult,
  LeadActivityItem,
  LeadActivitiesResult,
  BadgeStyle,
} from "@/lib/leads-presentation";
import {
  stageBadgeStyle,
  scoreChipStyle,
  initialsFromName,
} from "@/lib/leads-presentation";

// Re-exported so existing server-side consumers (`leads-table.tsx`,
// `lib/dashboard.ts`, and this module's own test suite) can keep importing
// these pure, client-safe types/functions from `@/lib/leads` unchanged.
// `lead-drawer.tsx` (a Client Component) must import them from
// `@/lib/leads-presentation` directly instead -- see that file's header for
// why (this module is `server-only` and can't be reached from client code,
// even transitively for a type-only import, without triggering Next's
// "'server-only' cannot be imported from a Client Component" build error).
export type { LeadDetail, LeadDetailResult, LeadActivityItem, LeadActivitiesResult, BadgeStyle };
export { stageBadgeStyle, scoreChipStyle, initialsFromName };

/** The five canonical lead stages (pipeline.py STAGE_ORDER + TERMINAL_STAGES). */
export const LEAD_STAGES = [
  "captured",
  "qualified",
  "contacted",
  "converted",
  "disqualified",
] as const;

export type LeadStage = (typeof LEAD_STAGES)[number];

/** The four canonical lead statuses (pipeline.py _STATUS_BY_STAGE values). */
export const LEAD_STATUSES = ["new", "open", "won", "lost"] as const;

export type LeadStatus = (typeof LEAD_STATUSES)[number];

/** Fixed page size for the console's Prev/Next pagination (decision 3, Q1). */
export const LEADS_PAGE_SIZE = 25;

/** A single row of `GET /admin/leads` -- mirrors `LeadListItem`
 * (admin_routes.py:136-140) exactly. No `tenant_id`/`visitor_id`/consent --
 * the backend response is already leak-free by construction. */
export interface LeadListItem {
  leadId: string;
  name: string;
  email: string;
  phone: string | null;
  status: string;
  stage: string;
  qualificationScore: number | null;
  assignedAgentId: string | null;
  source: string;
  createdAt: string;
}

interface LeadListItemResponseBody {
  lead_id: string;
  name: string;
  email: string;
  phone: string | null;
  status: string;
  stage: string;
  qualification_score: number | null;
  assigned_agent_id: string | null;
  source: string;
  created_at: string;
}

interface LeadListResponseBody {
  items: LeadListItemResponseBody[];
  total: number;
  limit: number;
  offset: number;
}

export type LeadsResult =
  | { status: "ok"; items: LeadListItem[]; total: number; limit: number; offset: number }
  | { status: "error"; message: string; correlationId: string };

export interface LeadsQueryParams {
  page: number;
  stage?: string;
}

/**
 * Pure, unit-testable query builder (decision 3/5). Clamps `page >= 1`,
 * derives `offset = (page-1) * LEADS_PAGE_SIZE`, and drops any `stage` value
 * not in `LEAD_STAGES` (unknown/blank -> no stage filter at all, so a
 * stray/hand-edited `?stage=bogus` degrades to "no filter" rather than a
 * hard 422 on first paint -- Decision 5's belt-and-suspenders is the 422
 * mapping in `listLeads` below, for the rare case a bad value still reaches
 * the backend).
 */
export function buildLeadsQuery(params: LeadsQueryParams): string {
  const page = Number.isFinite(params.page) && params.page >= 1 ? Math.floor(params.page) : 1;
  const offset = (page - 1) * LEADS_PAGE_SIZE;

  const query = new URLSearchParams();
  query.set("limit", String(LEADS_PAGE_SIZE));
  query.set("offset", String(offset));

  const stage = params.stage?.trim();
  if (stage && (LEAD_STAGES as readonly string[]).includes(stage)) {
    query.set("stage", stage);
  }

  return query.toString();
}

function toLeadListItem(body: LeadListItemResponseBody): LeadListItem {
  return {
    leadId: body.lead_id,
    name: body.name,
    email: body.email,
    phone: body.phone,
    status: body.status,
    stage: body.stage,
    qualificationScore: body.qualification_score,
    assignedAgentId: body.assigned_agent_id,
    source: body.source,
    createdAt: body.created_at,
  };
}

/**
 * Fetch a page of the caller's tenant leads. Never sends a `tenant_id` --
 * scoping is entirely the backend's repository-layer job from the caller's
 * own claims (CLAUDE.md §3). Never logs the response body (PII-minimal).
 *
 * `tenantId` (S13.7): when provided, targets the S12.7 PLATFORM_ADMIN
 * super-user surface `GET /admin/tenants/{tenantId}/leads` instead of the
 * implicit `GET /admin/leads` -- same response shape
 * (admin_routes.py `_list_leads`), only the URL prefix differs. Always the
 * route segment's `{tenantId}`, never client state (D1).
 */
export async function listLeads(
  params: LeadsQueryParams,
  tenantId?: string
): Promise<LeadsResult> {
  const query = buildLeadsQuery(params);
  const basePath = tenantId
    ? `/admin/tenants/${encodeURIComponent(tenantId)}/leads`
    : "/admin/leads";

  try {
    const response = await adminApiFetch(`${basePath}?${query}`);
    const body = (await response.json()) as LeadListResponseBody;
    return {
      status: "ok",
      items: body.items.map(toLeadListItem),
      total: body.total,
      limit: body.limit,
      offset: body.offset,
    };
  } catch (error) {
    if (error instanceof AdminApiError) {
      return { status: "error", message: mapErrorMessage(error), correlationId: error.correlationId };
    }
    // A network throw (not an AdminApiError) -- the request never reached
    // (or never returned from) admin-api.
    return {
      status: "error",
      message: "Unable to reach the server. Please try again.",
      correlationId: "",
    };
  }
}

function mapErrorMessage(error: AdminApiError): string {
  if (error.status === 403 || error.errorCode === "ROLE_NOT_PERMITTED") {
    return "You do not have permission to review leads.";
  }
  if (error.status === 401) {
    return "Your session has expired. Please log in again.";
  }
  if (error.errorCode === "INVALID_LEAD_FILTER" || error.errorCode === "INVALID_LIST_WINDOW") {
    return "That filter isn't valid -- showing all leads.";
  }
  return `Something went wrong (${error.errorCode || "UNKNOWN_ERROR"}). Correlation ID: ${
    error.correlationId || "n/a"
  }.`;
}

function mapDetailErrorMessage(error: AdminApiError): string {
  if (error.status === 404 || error.errorCode === "NOT_FOUND") {
    return "This lead could not be found.";
  }
  if (error.status === 403 || error.errorCode === "ROLE_NOT_PERMITTED") {
    return "You do not have permission to view this lead.";
  }
  if (error.status === 401) {
    return "Your session has expired. Please log in again.";
  }
  return `Something went wrong (${error.errorCode || "UNKNOWN_ERROR"}). Correlation ID: ${
    error.correlationId || "n/a"
  }.`;
}

// ---------------------------------------------------------------------------
// Lead detail drawer (4b) -- GET /admin/leads/{lead_id} and
// GET /admin/leads/{lead_id}/activities. Both mirror `admin_routes.py`'s
// leak-free response shapes exactly (no `tenant_id`). There is intentionally
// no transcript endpoint in this router (leads are not linked to a
// conversation_id anywhere server-side yet) -- the drawer's Transcript tab
// therefore has no real data source and must show an honest "not available"
// state rather than fabricate one (CLAUDE.md §3, no silent fallbacks).
// ---------------------------------------------------------------------------

interface LeadDetailResponseBody {
  lead_id: string;
  name: string;
  email: string;
  phone: string | null;
  status: string;
  stage: string;
  qualification_score: number | null;
  assigned_agent_id: string | null;
  source: string;
}

function toLeadDetail(body: LeadDetailResponseBody): LeadDetail {
  return {
    leadId: body.lead_id,
    name: body.name,
    email: body.email,
    phone: body.phone,
    status: body.status,
    stage: body.stage,
    qualificationScore: body.qualification_score,
    assignedAgentId: body.assigned_agent_id,
    source: body.source,
  };
}

/** Fetch a single lead's detail for the drawer's Details tab. Mirrors
 * `listLeads`'s tenant-scoped-path convention exactly. */
export async function getLeadDetail(
  leadId: string,
  tenantId?: string
): Promise<LeadDetailResult> {
  const basePath = tenantId
    ? `/admin/tenants/${encodeURIComponent(tenantId)}/leads`
    : "/admin/leads";

  try {
    const response = await adminApiFetch(`${basePath}/${encodeURIComponent(leadId)}`);
    const body = (await response.json()) as LeadDetailResponseBody;
    return { status: "ok", lead: toLeadDetail(body) };
  } catch (error) {
    if (error instanceof AdminApiError) {
      return { status: "error", message: mapDetailErrorMessage(error), correlationId: error.correlationId };
    }
    return {
      status: "error",
      message: "Unable to reach the server. Please try again.",
      correlationId: "",
    };
  }
}

interface LeadActivityResponseBody {
  activity_id: string;
  lead_id: string;
  type: string;
  payload: Record<string, unknown> | null;
  actor: string | null;
  created_at: string;
}

function toLeadActivityItem(body: LeadActivityResponseBody): LeadActivityItem {
  return {
    activityId: body.activity_id,
    leadId: body.lead_id,
    type: body.type,
    payload: body.payload,
    actor: body.actor,
    createdAt: body.created_at,
  };
}

/** Fetch a lead's full timeline for the drawer's Activity tab. The Notes tab
 * reuses this same call, filtered client-side to `type === "note"` -- the
 * backend has no separate notes-only GET route. */
export async function getLeadActivities(
  leadId: string,
  tenantId?: string
): Promise<LeadActivitiesResult> {
  const basePath = tenantId
    ? `/admin/tenants/${encodeURIComponent(tenantId)}/leads`
    : "/admin/leads";

  try {
    const response = await adminApiFetch(
      `${basePath}/${encodeURIComponent(leadId)}/activities`
    );
    const body = (await response.json()) as LeadActivityResponseBody[];
    return { status: "ok", items: body.map(toLeadActivityItem) };
  } catch (error) {
    if (error instanceof AdminApiError) {
      return { status: "error", message: mapDetailErrorMessage(error), correlationId: error.correlationId };
    }
    return {
      status: "error",
      message: "Unable to reach the server. Please try again.",
      correlationId: "",
    };
  }
}

// 4b design tokens (badge/score/initials helpers) now live in
// `@/lib/leads-presentation` (client-safe) and are re-exported at the top of
// this file for backwards compatibility with existing server-side imports.
