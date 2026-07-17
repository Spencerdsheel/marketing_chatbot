"use server";

/**
 * PLATFORM_ADMIN platform-level server actions (D7): onboard a new client +
 * rotate an existing client's key. Both wrap the unchanged
 * `POST /admin/tenants` / `POST /admin/tenants/{tenantId}/rotate-key` routes
 * via `lib/clients.ts`'s thin helpers.
 *
 * Secrets hygiene (highest priority, matching tenants/new/actions.ts's
 * established pattern): the one-time `client_key`/`admin_password` are
 * returned to the caller as `useActionState` result state and are NEVER
 * logged here, not even on error paths (only `error_code`/`correlation_id`/
 * `message` are logged/rendered).
 */
import { revalidatePath } from "next/cache";
import { AdminApiError } from "@/lib/api";
import { onboardClient, rotateClientKey } from "@/lib/clients";
import { onboardTenantFormSchema } from "@/lib/tenant-schema";

// ---------------------------------------------------------------------------
// onboardNewClient -- mirrors tenants/new/actions.ts's onboardTenant exactly
// (same form shape, same schema, same secrets-hygiene contract), reused here
// so the "Add client" action on the client list has identical behavior
// (D7: this is the co-located expression of the same platform-level power,
// not a second, divergent implementation).
// ---------------------------------------------------------------------------

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
  formError: string | null;
  partialCreationWarning: string | null;
  correlationId: string | null;
}

export interface OnboardIdleResult {
  status: "idle";
}

export type OnboardState = OnboardIdleResult | OnboardErrorResult | OnboardCreatedResult;

const GENERIC_NETWORK_ERROR = "Unable to reach the server. Please try again.";

function errorState(partial: Omit<OnboardErrorResult, "status">): OnboardErrorResult {
  return { status: "error", ...partial };
}

export async function onboardNewClient(
  _prevState: OnboardState,
  formData: FormData
): Promise<OnboardState> {
  const nullToUndefined = (value: FormDataEntryValue | null): string | undefined =>
    value === null ? undefined : String(value);

  const parsed = onboardTenantFormSchema.safeParse({
    name: formData.get("name"),
    slug: formData.get("slug"),
    adminEmail: formData.get("adminEmail"),
    adminName: nullToUndefined(formData.get("adminName")),
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

  const { name, slug, adminEmail, adminName, autoGeneratePassword, adminPassword } = parsed.data;

  let body: Awaited<ReturnType<typeof onboardClient>>;
  try {
    body = await onboardClient({
      name,
      slug,
      adminEmail,
      adminName,
      // Omit admin_password entirely when auto-generate is on -- the backend
      // generates one and echoes it back exactly once.
      adminPassword: autoGeneratePassword ? undefined : adminPassword,
    });
  } catch (err) {
    if (err instanceof AdminApiError) {
      return mapOnboardError(err, { name, slug });
    }
    return errorState({
      fieldErrors: {},
      formError: GENERIC_NETWORK_ERROR,
      partialCreationWarning: null,
      correlationId: null,
    });
  }

  revalidatePath("/clients");

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

function mapOnboardError(
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

  if (err.status === 403 || err.errorCode === "AUTHORIZATION_ERROR" || err.errorCode === "ROLE_NOT_PERMITTED") {
    return errorState({
      fieldErrors: {},
      formError: "You do not have permission to onboard clients.",
      partialCreationWarning: null,
      correlationId: err.correlationId || null,
    });
  }

  if (err.status === 401) {
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

// ---------------------------------------------------------------------------
// rotateKey -- the D7 rotate-key control on a client's screen.
// ---------------------------------------------------------------------------

export interface RotateKeyIdleState {
  status: "idle";
}

export interface RotateKeyErrorState {
  status: "error";
  message: string;
  correlationId: string | null;
}

export interface RotateKeyRotatedState {
  status: "rotated";
  tenantId: string;
  clientKey: string;
}

export type RotateKeyState = RotateKeyIdleState | RotateKeyErrorState | RotateKeyRotatedState;

/**
 * `tenantId` is bound via `rotateKeyForClient.bind(null, tenantId)` from the
 * per-client layout -- the SAME pattern as `uploadKnowledge`'s bound
 * argument. `tenantId` always comes from the route segment the control is
 * rendered under (D1), never form input.
 */
export async function rotateKeyForClient(
  tenantId: string,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  _prevState: RotateKeyState
): Promise<RotateKeyState> {
  let body: Awaited<ReturnType<typeof rotateClientKey>>;
  try {
    body = await rotateClientKey(tenantId);
  } catch (err) {
    if (err instanceof AdminApiError) {
      return mapRotateError(err);
    }
    return { status: "error", message: GENERIC_NETWORK_ERROR, correlationId: null };
  }

  revalidatePath(`/clients/${tenantId}`);

  return { status: "rotated", tenantId: body.tenant_id, clientKey: body.client_key };
}

function mapRotateError(err: AdminApiError): RotateKeyErrorState {
  if (err.status === 404 || err.errorCode === "TENANT_NOT_FOUND") {
    return {
      status: "error",
      message: "That client no longer exists.",
      correlationId: err.correlationId || null,
    };
  }
  if (err.status === 403 || err.errorCode === "AUTHORIZATION_ERROR" || err.errorCode === "ROLE_NOT_PERMITTED") {
    return {
      status: "error",
      message: "You do not have permission to rotate this client's key.",
      correlationId: err.correlationId || null,
    };
  }
  if (err.status === 401) {
    return {
      status: "error",
      message: "Your session has expired. Please sign in again.",
      correlationId: err.correlationId || null,
    };
  }
  return {
    status: "error",
    message: `${err.message} (correlation ID: ${err.correlationId || "unknown"})`,
    correlationId: err.correlationId || null,
  };
}
