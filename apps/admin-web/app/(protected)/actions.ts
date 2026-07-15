"use server";

/**
 * Logout server action (S13.1 scope item 6). Mirrors the login bridge:
 * calls admin-api's POST /auth/logout forwarding our own `access_token`
 * cookie (so the backend can blacklist the real `jti`), then clears this
 * app's own cookie regardless of the backend call's outcome -- a visitor
 * must never be stuck "logged in" locally just because the backend call
 * failed (e.g. Redis down for blacklist writes).
 */
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { adminApiFetch, AdminApiError } from "@/lib/api";
import { ACCESS_TOKEN_COOKIE } from "@/lib/auth";
import { PROFILE_COOKIE } from "@/lib/profile";

export async function logout(): Promise<void> {
  try {
    await adminApiFetch("/auth/logout", { method: "POST" });
  } catch (err) {
    // Best-effort: even if the backend call fails (e.g. token already
    // expired/blacklisted, or the backend is unreachable), still clear the
    // local session below -- never leave the browser holding a cookie that
    // renders the app as "logged in" when the user asked to log out.
    if (!(err instanceof AdminApiError)) {
      // Unexpected (network) failure -- log for observability; still proceed.
      console.error("logout: admin-api call failed", err);
    }
  }

  const cookieStore = await cookies();
  cookieStore.delete(ACCESS_TOKEN_COOKIE);
  cookieStore.delete(PROFILE_COOKIE);

  redirect("/login");
}
