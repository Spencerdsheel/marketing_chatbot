/**
 * Server-only environment configuration, validated eagerly (fail-fast) on
 * first import. Mirrors the backend's Pydantic Settings convention
 * (CLAUDE.md §config: "validate at startup; fail fast on missing required
 * config").
 *
 * Neither `ADMIN_API_BASE_URL` nor `JWT_SECRET` may ever be read via a
 * `NEXT_PUBLIC_*` variable -- that would bundle them into client JS. This
 * module is imported only from server-only code (server actions, route
 * handlers, `proxy.ts`, server components).
 */
import "server-only";

function required(name: string): string {
  const value = process.env[name];
  if (!value || value.trim().length === 0) {
    throw new Error(
      `Missing required environment variable: ${name}. See .env.example.`
    );
  }
  return value;
}

export const env = {
  /** Base URL of the running admin-api backend, e.g. http://localhost:8000 */
  adminApiBaseUrl: required("ADMIN_API_BASE_URL").replace(/\/+$/, ""),
  /**
   * HS256 secret used to verify JWTs minted by admin-api. MUST match the
   * backend's own `jwt_secret` (services/api/src/api/config.py), since we
   * verify tokens the backend minted -- never mint our own.
   */
  jwtSecret: required("JWT_SECRET"),
} as const;
