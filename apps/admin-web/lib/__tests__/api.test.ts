import { afterEach, describe, expect, it, vi } from "vitest";

const getMock = vi.fn();

vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({
    get: getMock,
  })),
}));

// Imported after the mock is registered so the module under test picks up
// the mocked `next/headers`.
const { adminApiFetch, AdminApiError } = await import("@/lib/api");

describe("adminApiFetch", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    getMock.mockReset();
  });

  it("attaches the access_token cookie as a Cookie header when present", async () => {
    getMock.mockReturnValue({ value: "jwt-value-123" });
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));

    await adminApiFetch("/auth/me");

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/auth/me");
    const headers = new Headers(init.headers);
    expect(headers.get("Cookie")).toBe("access_token=jwt-value-123");
  });

  it("omits the Cookie header when no cookie is present", async () => {
    getMock.mockReturnValue(undefined);
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response("{}", { status: 200 }));

    await adminApiFetch("/auth/me");

    const [, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(headers.has("Cookie")).toBe(false);
  });

  it("throws AdminApiError carrying error_code/correlation_id on non-2xx", async () => {
    getMock.mockReturnValue({ value: "jwt-value-123" });
    const errorBody = {
      error_code: "AUTHENTICATION_ERROR",
      message: "Invalid email or password.",
      correlation_id: "corr-abc-123",
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(errorBody), { status: 401 })
    );

    await expect(adminApiFetch("/auth/login")).rejects.toMatchObject({
      status: 401,
      errorCode: "AUTHENTICATION_ERROR",
      correlationId: "corr-abc-123",
      message: "Invalid email or password.",
    });
  });

  it("throws an AdminApiError instance specifically", async () => {
    getMock.mockReturnValue(undefined);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ error_code: "X", message: "y", correlation_id: "z" }),
        { status: 500 }
      )
    );

    await expect(adminApiFetch("/x")).rejects.toBeInstanceOf(AdminApiError);
  });

  it("falls back to a synthetic error body when the error response isn't JSON", async () => {
    getMock.mockReturnValue(undefined);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("not json", { status: 503 })
    );

    await expect(adminApiFetch("/x")).rejects.toMatchObject({
      status: 503,
      errorCode: "UNKNOWN_ERROR",
    });
  });
});
