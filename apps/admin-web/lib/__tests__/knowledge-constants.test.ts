import { describe, expect, it } from "vitest";
import {
  ALLOWED_CONTENT_TYPES,
  ALLOWED_EXTENSIONS,
  MAX_UPLOAD_BYTES,
  formatRunErrors,
  isTerminalRunStatus,
} from "@/lib/knowledge-constants";

describe("knowledge-constants", () => {
  it("MAX_UPLOAD_BYTES matches the real backend limit (config.py's ingestion_max_upload_bytes)", () => {
    expect(MAX_UPLOAD_BYTES).toBe(10_485_760);
  });

  it("ALLOWED_CONTENT_TYPES contains the two real backend content types", () => {
    expect(ALLOWED_CONTENT_TYPES).toContain("text/plain");
    expect(ALLOWED_CONTENT_TYPES).toContain(
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    );
    expect(ALLOWED_CONTENT_TYPES).toHaveLength(2);
  });

  it("ALLOWED_EXTENSIONS allows .txt and .docx", () => {
    expect(ALLOWED_EXTENSIONS).toContain(".txt");
    expect(ALLOWED_EXTENSIONS).toContain(".docx");
    expect(ALLOWED_EXTENSIONS).not.toContain(".png");
  });

  describe("isTerminalRunStatus", () => {
    it("treats queued/running as non-terminal", () => {
      expect(isTerminalRunStatus("queued")).toBe(false);
      expect(isTerminalRunStatus("running")).toBe(false);
    });

    it("treats succeeded/failed as terminal", () => {
      expect(isTerminalRunStatus("succeeded")).toBe(true);
      expect(isTerminalRunStatus("failed")).toBe(true);
    });
  });

  describe("formatRunErrors", () => {
    it("renders a list of strings", () => {
      const out = formatRunErrors(["chunk 3 failed to embed", "timeout on chunk 7"]);
      expect(out).toContain("chunk 3 failed to embed");
      expect(out).toContain("timeout on chunk 7");
    });

    it("renders a dict", () => {
      const out = formatRunErrors({ stage: "embed", message: "provider timeout" });
      expect(out).toContain("embed");
      expect(out).toContain("provider timeout");
    });

    it("renders null/undefined without throwing", () => {
      expect(() => formatRunErrors(null)).not.toThrow();
      expect(() => formatRunErrors(undefined)).not.toThrow();
      expect(formatRunErrors(null)).toMatch(/no error detail/i);
      expect(formatRunErrors(undefined)).toMatch(/no error detail/i);
    });

    it("renders a list of mixed shapes without throwing", () => {
      expect(() => formatRunErrors([{ code: "X" }, "plain string", 42])).not.toThrow();
    });
  });
});
