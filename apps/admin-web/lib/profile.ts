/**
 * Server-only helper for the caller's display profile (email/name).
 *
 * Deviation note (S13.1): the spec's placeholder shell shows
 * "Logged in as {email}", but neither the JWT (`sub`, `role`, `tenant_id`,
 * `project_ids` -- see api/auth/tokens.py) nor `GET /auth/me`
 * (`MeResponse`: `subject, role, tenant_id, project_ids` -- see
 * api/auth/routes.py) carries email. Email only appears in the one-time
 * `POST /auth/login` response body (`LoginProfile`). To show it on later
 * page loads without re-calling /auth/login, we capture it into a second,
 * small httpOnly cookie at login time -- NOT part of the JWT/auth-bridge
 * cookie, purely a display convenience. Email is not secret (the user
 * already knows their own email), so this does not weaken the security
 * property this sprint exists to prove (the JWT itself never leaves
 * server-side httpOnly storage). Cleared on logout alongside the access
 * token.
 */
import "server-only";

import { cookies } from "next/headers";

export const PROFILE_COOKIE = "user_profile";

export interface DisplayProfile {
  email: string;
  name: string | null;
}

export async function getProfile(): Promise<DisplayProfile | null> {
  const cookieStore = await cookies();
  const raw = cookieStore.get(PROFILE_COOKIE)?.value;
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<DisplayProfile>;
    if (typeof parsed.email !== "string") return null;
    return { email: parsed.email, name: parsed.name ?? null };
  } catch {
    return null;
  }
}
