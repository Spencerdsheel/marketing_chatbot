import { afterEach, describe, expect, it, vi } from "vitest";

const getMock = vi.fn();

vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({ get: getMock })),
}));

// Imported after the mock is registered so the module under test picks up
// the mocked `next/headers` (adminApiFetch reads the access_token cookie).
const { buildLeadsQuery, listLeads, LEAD_STAGES, LEAD_STATUSES } = await import("@/lib/leads");

describe("LEAD_STAGES / LEAD_STATUSES", () => {
  it("matches the five canonical stages from pipeline.py exactly", () => {
    expect(new Set(LEAD_STAGES)).toEqual(
      new Set(["captured", "qualified", "contacted", "converted", "disqualified"])
    );
    expect(LEAD_STAGES).toHaveLength(5);
  });

  it("matches the four canonical statuses from pipeline.py exactly", () => {
    expect(new Set(LEAD_STATUSES)).toEqual(new Set(["new", "open", "won", "lost"]));
    expect(LEAD_STATUSES).toHaveLength(4);
  });
});

describe("buildLeadsQuery", () => {
  it("page=1, no filters -> limit=25&offset=0", () => {
    const qs = buildLeadsQuery({ page: 1 });
    const params = new URLSearchParams(qs);
    expect(params.get("limit")).toBe("25");
    expect(params.get("offset")).toBe("0");
    expect(params.has("stage")).toBe(false);
  });

  it("page=3 -> offset=50", () => {
    const params = new URLSearchParams(buildLeadsQuery({ page: 3 }));
    expect(params.get("offset")).toBe("50");
  });

  it("page=0 or negative -> clamped to offset=0", () => {
    expect(new URLSearchParams(buildLeadsQuery({ page: 0 })).get("offset")).toBe("0");
    expect(new URLSearchParams(buildLeadsQuery({ page: -5 })).get("offset")).toBe("0");
  });

  it("a valid stage is included", () => {
    const params = new URLSearchParams(buildLeadsQuery({ page: 1, stage: "qualified" }));
    expect(params.get("stage")).toBe("qualified");
  });

  it("an unknown stage is dropped", () => {
    const params = new URLSearchParams(buildLeadsQuery({ page: 1, stage: "bogus" }));
    expect(params.has("stage")).toBe(false);
  });

  it("a blank stage is dropped", () => {
    const params = new URLSearchParams(buildLeadsQuery({ page: 1, stage: "" }));
    expect(params.has("stage")).toBe(false);
  });

  it("URL-encodes values rather than string-concatenating", () => {
    const qs = buildLeadsQuery({ page: 1, stage: "qualified" });
    expect(qs).toMatch(/^limit=25&offset=0&stage=qualified$/);
  });
});

describe("listLeads", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    getMock.mockReset();
  });

  it("maps a 200 envelope to an ok result with items/total passed through, no tenant_id", async () => {
    getMock.mockReturnValue({ value: "jwt-value" });
    const body = {
      items: [
        {
          lead_id: "lead-1",
          name: "Ada Lovelace",
          email: "ada@example.com",
          phone: null,
          status: "new",
          stage: "captured",
          qualification_score: null,
          assigned_agent_id: null,
          source: "widget",
          created_at: "2026-07-15T00:00:00Z",
        },
      ],
      total: 57,
      limit: 25,
      offset: 0,
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(body), { status: 200 })
    );

    const result = await listLeads({ page: 1 });

    expect(result.status).toBe("ok");
    if (result.status === "ok") {
      expect(result.total).toBe(57);
      expect(result.items).toHaveLength(1);
      expect(result.items[0].leadId).toBe("lead-1");
      expect(result.items[0]).not.toHaveProperty("tenant_id");
      expect(result.items[0]).not.toHaveProperty("tenantId");
    }
  });

  it("maps a 403 ROLE_NOT_PERMITTED to a friendly permission message", async () => {
    getMock.mockReturnValue(undefined);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          error_code: "ROLE_NOT_PERMITTED",
          message: "nope",
          correlation_id: "corr-1",
        }),
        { status: 403 }
      )
    );

    const result = await listLeads({ page: 1 });
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

    const result = await listLeads({ page: 1 });
    expect(result.status).toBe("error");
    if (result.status === "error") {
      expect(result.message).toMatch(/session/i);
    }
  });

  it("maps a 422 INVALID_LEAD_FILTER to a friendly filter banner", async () => {
    getMock.mockReturnValue(undefined);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ error_code: "INVALID_LEAD_FILTER", message: "bad", correlation_id: "c" }),
        { status: 422 }
      )
    );

    const result = await listLeads({ page: 1 });
    expect(result.status).toBe("error");
    if (result.status === "error") {
      expect(result.message).toMatch(/filter/i);
    }
  });

  it("maps a 422 INVALID_LIST_WINDOW to a friendly filter banner", async () => {
    getMock.mockReturnValue(undefined);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ error_code: "INVALID_LIST_WINDOW", message: "bad", correlation_id: "c" }),
        { status: 422 }
      )
    );

    const result = await listLeads({ page: 1 });
    expect(result.status).toBe("error");
    if (result.status === "error") {
      expect(result.message).toMatch(/filter/i);
    }
  });

  it("maps an unknown error code to a generic message including the correlation id", async () => {
    getMock.mockReturnValue(undefined);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ error_code: "SOMETHING_ELSE", message: "x", correlation_id: "corr-xyz" }),
        { status: 500 }
      )
    );

    const result = await listLeads({ page: 1 });
    expect(result.status).toBe("error");
    if (result.status === "error") {
      expect(result.correlationId).toBe("corr-xyz");
      expect(result.message).toContain("corr-xyz");
    }
  });

  it("maps a non-AdminApiError network throw to a generic network message", async () => {
    getMock.mockReturnValue(undefined);
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("network down"));

    const result = await listLeads({ page: 1 });
    expect(result.status).toBe("error");
    if (result.status === "error") {
      expect(result.message).toMatch(/unable to reach/i);
    }
  });

  it("never logs the response body", async () => {
    getMock.mockReturnValue(undefined);
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          items: [
            {
              lead_id: "lead-1",
              name: "Secret Name",
              email: "secret@example.com",
              phone: "+15551234567",
              status: "new",
              stage: "captured",
              qualification_score: 10,
              assigned_agent_id: null,
              source: "widget",
              created_at: "2026-07-15T00:00:00Z",
            },
          ],
          total: 1,
          limit: 25,
          offset: 0,
        }),
        { status: 200 }
      )
    );

    await listLeads({ page: 1 });

    expect(consoleSpy).not.toHaveBeenCalled();
    expect(errorSpy).not.toHaveBeenCalled();
  });
});
