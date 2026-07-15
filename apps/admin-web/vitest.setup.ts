// Test-only env values so lib/env.ts's fail-fast validation passes when the
// test suite imports modules that depend on it. Never used outside tests.
process.env.ADMIN_API_BASE_URL ??= "http://localhost:8000";
process.env.JWT_SECRET ??= "test-only-secret-at-least-32-characters-long!!";
