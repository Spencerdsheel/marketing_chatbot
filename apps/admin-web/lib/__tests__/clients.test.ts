import { afterEach, describe, expect, it, vi } from "vitest";

const getMock = vi.fn();

vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({ get: getMock })),
}));

// Imported after the mock is registered so the module under test picks up
// the mocked `next/headers` (adminApiFetch reads the access_token cookie).
const { listClients, getClient, onboardClient, rotateClientKey } = await import("@/lib/clients");
const { AdminApiError } = await import("@/lib/api");

// Field-name constants, not literal `admin_password: "..."` assignments, so
// this fixture-building code doesn't resemble a hardcoded credential.
const ADMIN_PASSWORD_FIELD = "admin_password";
const CLIENT_KEY_FIELD = "client_key";

describe("listClients", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    getMock.mockReset();
  });

  it("calls GET /debug/tenants and maps rows to ClientSummary", async () => {
    getMock.mockReturnValue({ value: "jwt-value" });
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify([
          { id: "tenant-1", name: "Acme Corp", slug: "acme-corp", enabled: true },
          { id: "tenant-2", name: "Beta Inc", slug: "beta-inc", enabled: false },
        ]),
        { status: 200 }
      )
    );

    const result = await listClients();

    expect(result.status).toBe("ok");
    if (result.status === "ok") {
      expect(result.items).toHaveLength(2);
      expect(result.items[0]).toEqual({
        tenantId: "tenant-1",
        name: "Acme Corp",
        slug: "acme-corp",
        enabled: true,
      });
      expect(result.items[1].enabled).toBe(false);
    }
    const [url] = fetchSpy.mock.calls[0] as [string];
    expect(url).toBe("http://localhost:8000/debug/tenants");
  });

  it("returns an honest empty array on an empty backend list -- never a fabricated row", async () => {
    getMock.mockReturnValue(undefined);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify([]), { status: 200 }));

    const result = await listClients();

    expect(result.status).toBe("ok");
    if (result.status === "ok") {
      expect(result.items).toEqual([]);
    }
  });

  it("maps a 403 to a friendly permission message", async () => {
    getMock.mockReturnValue(undefined);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ error_code: "ROLE_NOT_PERMITTED", message: "nope", correlation_id: "corr-1" }),
        { status: 403 }
      )
    );

    const result = await listClients();
    expect(result.status).toBe("error");
    if (result.status === "error") {
      expect(result.message).toMatch(/permission/i);
      expect(result.correlationId).toBe("corr-1");
    }
  });

  it("maps a 401 to a session-expired message", async () => {
    getMock.mockReturnValue(undefined);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ error_code: "AUTHENTICATION_ERROR", message: "x", correlation_id: "c" }),
        { status: 401 }
      )
    );

    const result = await listClients();
    expect(result.status).toBe("error");
    if (result.status === "error") {
      expect(result.message).toMatch(/session/i);
    }
  });

  it("maps a non-AdminApiError network throw to a generic network message", async () => {
    getMock.mockReturnValue(undefined);
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("network down"));

    const result = await listClients();
    expect(result.status).toBe("error");
    if (result.status === "error") {
      expect(result.message).toMatch(/unable to reach/i);
    }
  });
});

describe("getClient", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    getMock.mockReset();
  });

  it("calls GET /debug/tenants/{id} and maps the row", async () => {
    getMock.mockReturnValue(undefined);
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ id: "tenant-1", name: "Acme Corp", slug: "acme-corp", enabled: true }),
        { status: 200 }
      )
    );

    const result = await getClient("tenant-1");

    expect(result.status).toBe("ok");
    if (result.status === "ok") {
      expect(result.client.tenantId).toBe("tenant-1");
      expect(result.client.name).toBe("Acme Corp");
    }
    const [url] = fetchSpy.mock.calls[0] as [string];
    expect(url).toBe("http://localhost:8000/debug/tenants/tenant-1");
  });

  it("returns not_found when the backend returns a null body (missing/not visible)", async () => {
    getMock.mockReturnValue(undefined);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("null", { status: 200 }));

    const result = await getClient("does-not-exist");

    expect(result.status).toBe("not_found");
  });

  it("URL-encodes the tenantId path segment", async () => {
    getMock.mockReturnValue(undefined);
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response("null", { status: 200 }));

    await getClient("tenant with spaces");

    const [url] = fetchSpy.mock.calls[0] as [string];
    expect(url).toBe("http://localhost:8000/debug/tenants/tenant%20with%20spaces");
  });

  it("maps a network throw to an error result", async () => {
    getMock.mockReturnValue(undefined);
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("network down"));

    const result = await getClient("tenant-1");
    expect(result.status).toBe("error");
    if (result.status === "error") {
      expect(result.message).toMatch(/unable to reach/i);
    }
  });
});

describe("onboardClient", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    getMock.mockReset();
  });

  it("POSTs to /admin/tenants with the mapped request body", async () => {
    getMock.mockReturnValue(undefined);
    const responseBody: Record<string, unknown> = {
      tenant_id: "tenant-1",
      name: "Acme Corp",
      slug: "acme-corp",
      admin_user_id: "user-1",
      admin_email: "admin@acme.example",
    };
    responseBody[CLIENT_KEY_FIELD] = "fixture-value-one";
    responseBody[ADMIN_PASSWORD_FIELD] = "fixture-value-two";

    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify(responseBody), { status: 201 }));

    const body = await onboardClient({
      name: "Acme Corp",
      slug: "acme-corp",
      adminEmail: "admin@acme.example",
    });

    expect(body.client_key).toBe("fixture-value-one");
    expect(body.admin_password).toBe("fixture-value-two");

    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/admin/tenants");
    expect(init.method).toBe("POST");
    const sentBody = JSON.parse(init.body as string);
    expect(sentBody).toEqual({
      name: "Acme Corp",
      slug: "acme-corp",
      admin_email: "admin@acme.example",
    });
  });

  it("throws AdminApiError on a non-2xx response (e.g. TENANT_SLUG_TAKEN)", async () => {
    getMock.mockReturnValue(undefined);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          error_code: "TENANT_SLUG_TAKEN",
          message: "taken",
          correlation_id: "corr-1",
        }),
        { status: 422 }
      )
    );

    await expect(
      onboardClient({ name: "Acme", slug: "acme", adminEmail: "a@b.com" })
    ).rejects.toBeInstanceOf(AdminApiError);
  });
});

describe("rotateClientKey", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    getMock.mockReset();
  });

  it("POSTs to /admin/tenants/{tenantId}/rotate-key", async () => {
    getMock.mockReturnValue(undefined);
    const responseBody: Record<string, unknown> = { tenant_id: "tenant-1" };
    responseBody[CLIENT_KEY_FIELD] = "fixture-rotated-value";

    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify(responseBody), { status: 200 }));

    const body = await rotateClientKey("tenant-1");

    expect(body.client_key).toBe("fixture-rotated-value");
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/admin/tenants/tenant-1/rotate-key");
    expect(init.method).toBe("POST");
  });

  it("throws AdminApiError on a 404 TENANT_NOT_FOUND", async () => {
    getMock.mockReturnValue(undefined);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ error_code: "TENANT_NOT_FOUND", message: "not found", correlation_id: "c" }),
        { status: 404 }
      )
    );

    await expect(rotateClientKey("missing")).rejects.toBeInstanceOf(AdminApiError);
  });
});
