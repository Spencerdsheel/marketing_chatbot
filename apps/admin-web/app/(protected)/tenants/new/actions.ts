"use server";

/**
 * Tenant onboarding server action (S13.2 decisions 2-4). Validates with the
 * shared Zod schema (courtesy pre-check; the backend is authoritative), then
 * calls `POST /admin/tenants` via `adminApiFetch`.
 *
 * Secrets hygiene (highest priority, decision 3): the response body --
 * which carries the one-time `client_key` and (maybe) `admin_password` --
 * is returned to the client as `useActionState` state and is NEVER logged
 * here, not even on error paths (only `error_code`/`correlation_id`/
 * `message` from `AdminApiError` are logged/rendered, never a response
 * body).
 */
import { AdminApiError, adminApiFetch } from "@/lib/api";
import { onboardTenantFormSchema } from "@/lib/tenant-schema";

export interface OnboardFieldErrors {
  name?: string;
  slug?: string;
  adminEmail?: string;
  adminName?: string;
  adminPassword?: string;
}

export interface OnboardCreatedResult {
  status: "created";
  tenant: {
    tenantId: string;
    name: string;
    slug: string;
    adminUserId: string;
    adminEmail: string;
  };
  clientKey: string;
  generatedPassword: string | null;
}

export interface OnboardErrorResult {
  status: "error";
  fieldErrors: OnboardFieldErrors;
  /** General/banner-level message, when not tied to a single field. */
  formError: string | null;
  /** Set only for the ADMIN_EMAIL_TAKEN partial-creation disclosure. */
  partialCreationWarning: string | null;
  correlationId: string | null;
}

export interface OnboardIdleResult {
  status: "idle";
}

export type OnboardState =
  | OnboardIdleResult
  | OnboardErrorResult
  | OnboardCreatedResult;

interface AdminOnboardTenantResponseBody {
  tenant_id: string;
  name: string;
  slug: string;
  client_key: string;
  admin_user_id: string;
  admin_email: string;
  admin_password: string | null;
}

const GENERIC_NETWORK_ERROR = "Unable to reach the server. Please try again.";

function errorState(partial: Omit<OnboardErrorResult, "status">): OnboardErrorResult {
  return { status: "error", ...partial };
}

export async function onboardTenant(
  _prevState: OnboardState,
  formData: FormData
): Promise<OnboardState> {
  // FormData.get() returns `null` for an absent field, but Zod's
  // `.optional()` only accepts `undefined` (not `null`) -- normalize here so
  // an omitted admin name/password doesn't fail schema validation.
  const nullToUndefined = (value: FormDataEntryValue | null): string | undefined =>
    value === null ? undefined : String(value);

  const parsed = onboardTenantFormSchema.safeParse({
    name: formData.get("name"),
    slug: formData.get("slug"),
    adminEmail: formData.get("adminEmail"),
    adminName: nullToUndefined(formData.get("adminName")),
    // The Checkbox primitive's hidden input only submits a value when
    // checked (no `uncheckedValue` is set) -- presence, not a specific
    // string, is the signal. See onboard-form.tsx's Checkbox usage.
    autoGeneratePassword: formData.get("autoGeneratePassword") !== null,
    adminPassword: nullToUndefined(formData.get("adminPassword")),
  });

  if (!parsed.success) {
    const fieldErrors: OnboardFieldErrors = {};
    for (const issue of parsed.error.issues) {
      const key = issue.path[0];
      if (key === "name") fieldErrors.name ??= issue.message;
      else if (key === "slug") fieldErrors.slug ??= issue.message;
      else if (key === "adminEmail") fieldErrors.adminEmail ??= issue.message;
      else if (key === "adminName") fieldErrors.adminName ??= issue.message;
      else if (key === "adminPassword") fieldErrors.adminPassword ??= issue.message;
    }
    return errorState({
      fieldErrors,
      formError: Object.keys(fieldErrors).length === 0 ? "Check the form and try again." : null,
      partialCreationWarning: null,
      correlationId: null,
    });
  }

  const { name, slug, adminEmail, adminName, autoGeneratePassword, adminPassword } =
    parsed.data;

  const requestBody: Record<string, unknown> = {
    name,
    slug,
    admin_email: adminEmail,
  };
  if (adminName) requestBody.admin_name = adminName;
  // Omit admin_password entirely when auto-generate is on -- the backend
  // generates one and echoes it back exactly once (decision 2).
  if (!autoGeneratePassword && adminPassword) {
    requestBody.admin_password = adminPassword;
  }

  let response: Response;
  try {
    response = await adminApiFetch("/admin/tenants", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody),
    });
  } catch (err) {
    if (err instanceof AdminApiError) {
      return mapAdminApiError(err, { name, slug });
    }
    // Network-level throw (not an AdminApiError) -- mirrors login/actions.ts.
    return errorState({
      fieldErrors: {},
      formError: GENERIC_NETWORK_ERROR,
      partialCreationWarning: null,
      correlationId: null,
    });
  }

  const body = (await response.json()) as AdminOnboardTenantResponseBody;

  return {
    status: "created",
    tenant: {
      tenantId: body.tenant_id,
      name: body.name,
      slug: body.slug,
      adminUserId: body.admin_user_id,
      adminEmail: body.admin_email,
    },
    clientKey: body.client_key,
    generatedPassword: body.admin_password,
  };
}

function mapAdminApiError(
  err: AdminApiError,
  attempted: { name: string; slug: string }
): OnboardErrorResult {
  if (err.errorCode === "TENANT_SLUG_TAKEN") {
    return errorState({
      fieldErrors: { slug: "That slug is already taken — choose another." },
      formError: null,
      partialCreationWarning: null,
      correlationId: err.correlationId || null,
    });
  }

  if (err.errorCode === "ADMIN_EMAIL_TAKEN") {
    return errorState({
      fieldErrors: { adminEmail: "That email is already in use." },
      formError: null,
      partialCreationWarning:
        `A tenant named '${attempted.name}' (slug '${attempted.slug}') was created, but the admin ` +
        "user was not — that email is already in use. The client key for this half-created tenant " +
        "was not shown and cannot be recovered; contact platform ops to complete or remove it, or " +
        "retry with a different slug and email.",
      correlationId: err.correlationId || null,
    });
  }

  if (err.status === 403 || err.errorCode === "AUTHORIZATION_ERROR") {
    return errorState({
      fieldErrors: {},
      formError: "You do not have permission to onboard tenants.",
      partialCreationWarning: null,
      correlationId: err.correlationId || null,
    });
  }

  if (err.status === 401) {
    // Treat as an expired session; consistent with S13.1's handling, the
    // next protected navigation will redirect to /login. No special message
    // needed here beyond the generic path below.
    return errorState({
      fieldErrors: {},
      formError: "Your session has expired. Please sign in again.",
      partialCreationWarning: null,
      correlationId: err.correlationId || null,
    });
  }

  return errorState({
    fieldErrors: {},
    formError: `${err.message} (correlation ID: ${err.correlationId || "unknown"})`,
    partialCreationWarning: null,
    correlationId: err.correlationId || null,
  });
}
