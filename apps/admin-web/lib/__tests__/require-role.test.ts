import { afterEach, describe, expect, it, vi } from "vitest";
import jwt from "jsonwebtoken";

const getMock = vi.fn();
const redirectMock = vi.fn((url: string) => {
  // Mirrors Next.js's real `redirect()`: throws to unwind the render, never
  // returns. Tests assert on the thrown sentinel's destination.
  throw new Error(`REDIRECT:${url}`);
});

vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({ get: getMock })),
}));

vi.mock("next/navigation", () => ({
  redirect: redirectMock,
}));

// Imported after the mocks are registered so the module under test picks up
// the mocked `next/headers` / `next/navigation`.
const { requireRole } = await import("@/lib/auth");

// Matches vitest.setup.ts.
const SECRET = process.env.JWT_SECRET as string;

function signToken(payload: Record<string, unknown>, opts: jwt.SignOptions = {}): string {
  return jwt.sign(payload, SECRET, { algorithm: "HS256", ...opts });
}

describe("requireRole", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("returns claims when the caller's role matches", async () => {
    const token = signToken(
      { sub: "admin-1", role: "PLATFORM_ADMIN", tenant_id: null, project_ids: [] },
      { expiresIn: "1h" }
    );
    getMock.mockReturnValue({ value: token });

    const claims = await requireRole("PLATFORM_ADMIN");

    expect(claims.role).toBe("PLATFORM_ADMIN");
    expect(redirectMock).not.toHaveBeenCalled();
  });

  it("redirects to / when authenticated with a non-matching role", async () => {
    const token = signToken(
      { sub: "user-1", role: "CLIENT_ADMIN", tenant_id: "tenant-1", project_ids: [] },
      { expiresIn: "1h" }
    );
    getMock.mockReturnValue({ value: token });

    await expect(requireRole("PLATFORM_ADMIN")).rejects.toThrow("REDIRECT:/");
    expect(redirectMock).toHaveBeenCalledWith("/");
  });

  it("redirects a CLIENT_AGENT away from a PLATFORM_ADMIN-only page", async () => {
    const token = signToken(
      { sub: "agent-1", role: "CLIENT_AGENT", tenant_id: "tenant-1", project_ids: [] },
      { expiresIn: "1h" }
    );
    getMock.mockReturnValue({ value: token });

    await expect(requireRole("PLATFORM_ADMIN")).rejects.toThrow("REDIRECT:/");
  });

  it("redirects to /login when unauthenticated (no cookie)", async () => {
    getMock.mockReturnValue(undefined);

    await expect(requireRole("PLATFORM_ADMIN")).rejects.toThrow("REDIRECT:/login");
    expect(redirectMock).toHaveBeenCalledWith("/login");
  });
});
