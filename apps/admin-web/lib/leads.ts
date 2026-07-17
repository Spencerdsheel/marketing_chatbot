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
