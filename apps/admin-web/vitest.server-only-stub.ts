// Test-only stub for the "server-only" package. Next.js's own bundler
// resolves "server-only" to a no-op on the server and to a throwing stub
// only when bundled into a client component. Vitest doesn't apply that
// same conditional resolution, so without this alias every module that
// imports "server-only" (lib/env.ts, lib/auth.ts, lib/api.ts, lib/
// profile.ts, proxy.ts) would fail to import under test even though none
// of them are ever bundled client-side in the real app. See
// vitest.config.ts's `resolve.alias`.
export {};
