import { afterEach, describe, expect, it, vi } from "vitest";

const adminApiFetchMock = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    adminApiFetch: (...args: unknown[]) => adminApiFetchMock(...args),
  };
});

const { uploadKnowledge, getDocStatus } = await import(
  "@/app/(protected)/knowledge/actions"
);
const { AdminApiError } = await import("@/lib/api");

function jsonResponse(body: Record<string, unknown>, status: number): Response {
  return new Response(JSON.stringify(body), { status });
}

function buildFormData(file: File | null): FormData {
  const fd = new FormData();
  if (file) fd.set("file", file);
  return fd;
}

function makeFile(opts: { name?: string; type?: string; sizeBytes?: number } = {}): File {
  const { name = "faq.txt", type = "text/plain", sizeBytes = 100 } = opts;
  const content = new Uint8Array(sizeBytes).fill(65); // 'A' repeated
  return new File([content], name, { type });
}

describe("uploadKnowledge", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    adminApiFetchMock.mockReset();
  });

  it("rejects a missing file client-side without calling adminApiFetch", async () => {
    const state = await uploadKnowledge(undefined, { status: "idle" }, buildFormData(null));

    expect(state.status).toBe("error");
    expect(adminApiFetchMock).not.toHaveBeenCalled();
  });

  it("rejects an oversized file in the server-action re-check without calling adminApiFetch", async () => {
    const oversized = makeFile({ sizeBytes: 10_485_761 });
    const state = await uploadKnowledge(undefined, { status: "idle" }, buildFormData(oversized));

    expect(state.status).toBe("error");
    if (state.status === "error") {
      expect(state.message).toMatch(/too large/i);
    }
    expect(adminApiFetchMock).not.toHaveBeenCalled();
  });

  it("rejects a disallowed content type in the server-action re-check without calling adminApiFetch", async () => {
    const badType = makeFile({ name: "logo.png", type: "image/png" });
    const state = await uploadKnowledge(undefined, { status: "idle" }, buildFormData(badType));

    expect(state.status).toBe("error");
    if (state.status === "error") {
      expect(state.message).toMatch(/unsupported file type/i);
    }
    expect(adminApiFetchMock).not.toHaveBeenCalled();
  });

  it("returns an uploaded state with idempotent:false on a fresh upload (run_id set)", async () => {
    adminApiFetchMock.mockResolvedValue(
      jsonResponse({ doc_id: "doc-1", run_id: "run-1", status: "pending" }, 200)
    );

    const state = await uploadKnowledge(undefined, { status: "idle" }, buildFormData(makeFile()));

    expect(state.status).toBe("uploaded");
    if (state.status === "uploaded") {
      expect(state.docId).toBe("doc-1");
      expect(state.runId).toBe("run-1");
      expect(state.idempotent).toBe(false);
    }
  });

  it("returns an uploaded state with idempotent:true when run_id is null", async () => {
    adminApiFetchMock.mockResolvedValue(
      jsonResponse({ doc_id: "doc-2", run_id: null, status: "parsed" }, 200)
    );

    const state = await uploadKnowledge(undefined, { status: "idle" }, buildFormData(makeFile()));

    expect(state.status).toBe("uploaded");
    if (state.status === "uploaded") {
      expect(state.docId).toBe("doc-2");
      expect(state.runId).toBeNull();
      expect(state.docStatus).toBe("parsed");
      expect(state.idempotent).toBe(true);
    }
  });

  it("maps UNSUPPORTED_CONTENT_TYPE to a friendly message", async () => {
    adminApiFetchMock.mockRejectedValue(
      new AdminApiError(422, {
        error_code: "UNSUPPORTED_CONTENT_TYPE",
        message: "Unsupported content type.",
        correlation_id: "corr-1",
      })
    );

    const state = await uploadKnowledge(undefined, { status: "idle" }, buildFormData(makeFile()));

    expect(state.status).toBe("error");
    if (state.status === "error") {
      expect(state.message).toMatch(/\.txt and \.docx/i);
    }
  });

  it("maps a 413 FILE_TOO_LARGE to a friendly message", async () => {
    adminApiFetchMock.mockRejectedValue(
      new AdminApiError(413, {
        error_code: "FILE_TOO_LARGE",
        message: "Upload exceeds the limit.",
        correlation_id: "corr-2",
      })
    );

    const state = await uploadKnowledge(undefined, { status: "idle" }, buildFormData(makeFile()));

    expect(state.status).toBe("error");
    if (state.status === "error") {
      expect(state.message).toMatch(/too large/i);
    }
  });

  it("maps a 403 ROLE_NOT_PERMITTED to a permission-denied message", async () => {
    adminApiFetchMock.mockRejectedValue(
      new AdminApiError(403, {
        error_code: "ROLE_NOT_PERMITTED",
        message: "Forbidden.",
        correlation_id: "corr-3",
      })
    );

    const state = await uploadKnowledge(undefined, { status: "idle" }, buildFormData(makeFile()));

    expect(state.status).toBe("error");
    if (state.status === "error") {
      expect(state.message).toMatch(/permission/i);
    }
  });

  it("maps a 401 to a session-expired message", async () => {
    adminApiFetchMock.mockRejectedValue(
      new AdminApiError(401, {
        error_code: "AUTHENTICATION_ERROR",
        message: "Expired.",
        correlation_id: "corr-4",
      })
    );

    const state = await uploadKnowledge(undefined, { status: "idle" }, buildFormData(makeFile()));

    expect(state.status).toBe("error");
    if (state.status === "error") {
      expect(state.message).toMatch(/session has expired/i);
    }
  });

  it("maps an unknown error code to a generic message including the correlation ID", async () => {
    adminApiFetchMock.mockRejectedValue(
      new AdminApiError(500, {
        error_code: "INTERNAL_SERVER_ERROR",
        message: "Something went wrong.",
        correlation_id: "corr-unknown-xyz",
      })
    );

    const state = await uploadKnowledge(undefined, { status: "idle" }, buildFormData(makeFile()));

    expect(state.status).toBe("error");
    if (state.status === "error") {
      expect(state.message).toContain("corr-unknown-xyz");
    }
  });

  it("returns a generic network message when adminApiFetch throws a non-AdminApiError", async () => {
    adminApiFetchMock.mockRejectedValue(new TypeError("fetch failed"));

    const state = await uploadKnowledge(undefined, { status: "idle" }, buildFormData(makeFile()));

    expect(state.status).toBe("error");
    if (state.status === "error") {
      expect(state.message).toMatch(/unable to reach the server/i);
    }
  });

  it("targets the implicit /admin/ingestion/upload path when tenantId is omitted", async () => {
    adminApiFetchMock.mockResolvedValue(
      jsonResponse({ doc_id: "doc-1", run_id: "run-1", status: "pending" }, 200)
    );

    await uploadKnowledge(undefined, { status: "idle" }, buildFormData(makeFile()));

    expect(adminApiFetchMock).toHaveBeenCalledWith(
      "/admin/ingestion/upload",
      expect.objectContaining({ method: "POST" })
    );
  });

  it("targets the S12.7 tenant-scoped path when tenantId is bound (PLATFORM_ADMIN)", async () => {
    adminApiFetchMock.mockResolvedValue(
      jsonResponse({ doc_id: "doc-1", run_id: "run-1", status: "pending" }, 200)
    );

    await uploadKnowledge("tenant-x", { status: "idle" }, buildFormData(makeFile()));

    expect(adminApiFetchMock).toHaveBeenCalledWith(
      "/admin/tenants/tenant-x/ingestion/upload",
      expect.objectContaining({ method: "POST" })
    );
  });
});

describe("getDocStatus", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    adminApiFetchMock.mockReset();
  });

  it("maps a 200 body with latest_run to a DocStatusOk with a run", async () => {
    adminApiFetchMock.mockResolvedValue(
      jsonResponse(
        {
          doc_id: "doc-1",
          filename: "faq.txt",
          content_type: "text/plain",
          status: "pending",
          content_hash: "abc",
          latest_run: {
            run_id: "run-1",
            status: "running",
            chars_out: null,
            errors: null,
            duration_ms: null,
          },
          parsed_preview: null,
        },
        200
      )
    );

    const result = await getDocStatus("doc-1");

    expect(result.status).toBe("ok");
    if (result.status === "ok") {
      expect(result.run?.status).toBe("running");
      expect(result.docStatus).toBe("pending");
    }
  });

  it("maps a 200 body without latest_run to a DocStatusOk with run: null", async () => {
    adminApiFetchMock.mockResolvedValue(
      jsonResponse(
        {
          doc_id: "doc-2",
          filename: "faq.txt",
          content_type: "text/plain",
          status: "pending",
          content_hash: "abc",
          latest_run: null,
          parsed_preview: null,
        },
        200
      )
    );

    const result = await getDocStatus("doc-2");

    expect(result.status).toBe("ok");
    if (result.status === "ok") {
      expect(result.run).toBeNull();
    }
  });

  it("maps a 404 DOC_NOT_FOUND to an error variant", async () => {
    adminApiFetchMock.mockRejectedValue(
      new AdminApiError(404, {
        error_code: "DOC_NOT_FOUND",
        message: "Not found.",
        correlation_id: "corr-5",
      })
    );

    const result = await getDocStatus("doc-missing");

    expect(result.status).toBe("error");
    if (result.status === "error") {
      expect(result.errorCode).toBe("DOC_NOT_FOUND");
    }
  });

  it("maps a network throw to an error variant", async () => {
    adminApiFetchMock.mockRejectedValue(new TypeError("fetch failed"));

    const result = await getDocStatus("doc-3");

    expect(result.status).toBe("error");
    if (result.status === "error") {
      expect(result.message).toMatch(/unable to reach the server/i);
    }
  });
});
