"use server";

/**
 * Lead drawer server actions (4b restyle). Only mutation the drawer needs is
 * adding a note -- `POST /admin/leads/{lead_id}/notes` (admin_routes.py:585).
 * Mirrors `knowledge/actions.ts`'s tenantId-bound-arg pattern so the same
 * action serves both the implicit CLIENT_ADMIN/AGENT route and the S12.7
 * PLATFORM_ADMIN tenant-scoped route.
 */
import { revalidatePath } from "next/cache";
import { AdminApiError, adminApiFetch } from "@/lib/api";

const GENERIC_NETWORK_ERROR = "Unable to reach the server. Please try again.";
const NOTE_MAX_LENGTH = 4000;

export interface AddNoteIdleState {
  status: "idle";
}

export interface AddNoteErrorState {
  status: "error";
  message: string;
}

export interface AddNoteOkState {
  status: "ok";
}

export type AddNoteState = AddNoteIdleState | AddNoteErrorState | AddNoteOkState;

/**
 * `tenantId`/`leadId`/`revalidatePathTarget` are bound via
 * `addLeadNote.bind(null, tenantId, leadId, path)` from the drawer's note
 * form (the same pattern `uploadKnowledge` uses for its bound `tenantId`).
 * `revalidatePathTarget` re-runs the server component so the Notes/Activity
 * tabs reflect the new note on next open without a full page reload.
 */
export async function addLeadNote(
  tenantId: string | undefined,
  leadId: string,
  revalidatePathTarget: string,
  _prevState: AddNoteState,
  formData: FormData
): Promise<AddNoteState> {
  const rawText = formData.get("text");
  const text = typeof rawText === "string" ? rawText.trim() : "";

  if (!text) {
    return { status: "error", message: "Note text must not be blank." };
  }
  if (text.length > NOTE_MAX_LENGTH) {
    return {
      status: "error",
      message: `Note is too long (max ${NOTE_MAX_LENGTH} characters).`,
    };
  }

  const basePath = tenantId
    ? `/admin/tenants/${encodeURIComponent(tenantId)}/leads`
    : "/admin/leads";

  try {
    await adminApiFetch(`${basePath}/${encodeURIComponent(leadId)}/notes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
  } catch (error) {
    if (error instanceof AdminApiError) {
      return { status: "error", message: mapNoteError(error) };
    }
    return { status: "error", message: GENERIC_NETWORK_ERROR };
  }

  revalidatePath(revalidatePathTarget);
  return { status: "ok" };
}

function mapNoteError(error: AdminApiError): string {
  if (error.status === 404 || error.errorCode === "NOT_FOUND") {
    return "This lead could not be found.";
  }
  if (error.status === 403 || error.errorCode === "ROLE_NOT_PERMITTED") {
    return "You do not have permission to add notes to leads.";
  }
  if (error.status === 401) {
    return "Your session has expired. Please log in again.";
  }
  return `${error.message} (correlation ID: ${error.correlationId || "unknown"}).`;
}
