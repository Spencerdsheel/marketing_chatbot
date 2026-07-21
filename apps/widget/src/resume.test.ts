/**
 * Tests for the resume-record read/write helper (SR-3 scope item 1).
 *
 * `resume.ts` is pure logic, no React -- `sessionStorage` + `Date` are the
 * only dependencies, both easily faked in jsdom/Vitest. Covers decision 4
 * (the record's exact key set -- the PII-minimization gate), decision 5 (the
 * 15-min inactivity TTL hard-capped by the token's own `expiresAt`), and
 * decision 7 (never throws -- a corrupt value or an unavailable
 * `sessionStorage` degrades to `null`/no-op, never breaks boot).
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  clearResumeRecord,
  readResumeRecord,
  RESUME_KEY,
  touchResumeRecord,
  writeResumeRecord,
  type ResumeRecord,
} from "./resume";

// Not a real credential -- a short fixture string used only to distinguish
// "a bearer value is present" from "absent" in the assertions below
// (mirrors entry.test.tsx's FIXTURE_SESSION_A/B convention).
const FIXTURE_BEARER = "fixture-visitor-bearer";

function record(overrides: Partial<ResumeRecord> = {}): ResumeRecord {
  return {
    token: FIXTURE_BEARER,
    expiresAt: "2026-07-20T13:00:00.000Z",
    conversationId: null,
    lastActive: "2026-07-20T12:00:00.000Z",
    ...overrides,
  };
}

describe("resume.ts", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  afterEach(() => {
    sessionStorage.clear();
  });

  describe("writeResumeRecord / readResumeRecord round-trip", () => {
    it("round-trips the token/expiresAt/conversationId within TTL", () => {
      const now = new Date("2026-07-20T12:05:00.000Z"); // 5 min after lastActive
      const rec = record({ conversationId: "conv-123" });
      writeResumeRecord(rec);

      const result = readResumeRecord(now);

      expect(result).toEqual(rec);
    });

    it("serializes to sessionStorage under the exact namespaced key", () => {
      writeResumeRecord(record());
      expect(sessionStorage.getItem(RESUME_KEY)).not.toBeNull();
      expect(RESUME_KEY).toBe("cw:resume:v1");
    });
  });

  describe("inactivity TTL (decision 5)", () => {
    it("returns null and REMOVES the key when lastActive is >15 min old", () => {
      const rec = record({
        lastActive: "2026-07-20T12:00:00.000Z",
        expiresAt: "2026-07-20T13:00:00.000Z", // token still valid
      });
      writeResumeRecord(rec);

      const now = new Date("2026-07-20T12:16:00.000Z"); // 16 min later
      const result = readResumeRecord(now);

      expect(result).toBeNull();
      expect(sessionStorage.getItem(RESUME_KEY)).toBeNull();
    });

    it("returns the record when lastActive is exactly at the 15-min boundary or under", () => {
      const rec = record({
        lastActive: "2026-07-20T12:00:00.000Z",
        expiresAt: "2026-07-20T13:00:00.000Z",
      });
      writeResumeRecord(rec);

      const now = new Date("2026-07-20T12:14:59.000Z"); // just under 15 min
      const result = readResumeRecord(now);

      expect(result).toEqual(rec);
    });
  });

  describe("token expiresAt ceiling (decision 5)", () => {
    it("returns null and removes the key when now >= expiresAt, even if lastActive is recent", () => {
      const rec = record({
        lastActive: "2026-07-20T12:00:00.000Z",
        expiresAt: "2026-07-20T12:00:30.000Z", // token expires 30s after lastActive
      });
      writeResumeRecord(rec);

      const now = new Date("2026-07-20T12:00:31.000Z"); // 31s later -- inactivity TTL not hit, token is
      const result = readResumeRecord(now);

      expect(result).toBeNull();
      expect(sessionStorage.getItem(RESUME_KEY)).toBeNull();
    });
  });

  describe("robustness (decision 7 -- never throws)", () => {
    it("a corrupt/non-JSON value returns null and removes the key, no throw", () => {
      sessionStorage.setItem(RESUME_KEY, "{not valid json");

      expect(() => readResumeRecord(new Date())).not.toThrow();
      expect(readResumeRecord(new Date())).toBeNull();
      expect(sessionStorage.getItem(RESUME_KEY)).toBeNull();
    });

    it("a value failing Zod validation (missing fields) returns null and removes the key", () => {
      sessionStorage.setItem(RESUME_KEY, JSON.stringify({ token: FIXTURE_BEARER }));

      const result = readResumeRecord(new Date());

      expect(result).toBeNull();
      expect(sessionStorage.getItem(RESUME_KEY)).toBeNull();
    });

    it("readResumeRecord in an environment where sessionStorage throws returns null, no throw", () => {
      const original = globalThis.sessionStorage;
      Object.defineProperty(globalThis, "sessionStorage", {
        configurable: true,
        get() {
          throw new DOMException("The operation is insecure.", "SecurityError");
        },
      });

      try {
        expect(() => readResumeRecord(new Date())).not.toThrow();
        expect(readResumeRecord(new Date())).toBeNull();
      } finally {
        Object.defineProperty(globalThis, "sessionStorage", {
          configurable: true,
          value: original,
        });
      }
    });

    it("writeResumeRecord is a silent no-op when sessionStorage throws (never breaks boot)", () => {
      const original = globalThis.sessionStorage;
      Object.defineProperty(globalThis, "sessionStorage", {
        configurable: true,
        get() {
          throw new DOMException("The operation is insecure.", "SecurityError");
        },
      });

      try {
        expect(() => writeResumeRecord(record())).not.toThrow();
      } finally {
        Object.defineProperty(globalThis, "sessionStorage", {
          configurable: true,
          value: original,
        });
      }
    });
  });

  describe("PII-minimization gate (decision 4 -- MANDATORY)", () => {
    it("the serialized JSON's key set is EXACTLY {token, expiresAt, conversationId, lastActive} -- never tenant_id/name/email/phone/message content", () => {
      writeResumeRecord(record({ conversationId: "conv-abc" }));

      const raw = sessionStorage.getItem(RESUME_KEY);
      expect(raw).not.toBeNull();
      const parsed = JSON.parse(raw as string) as Record<string, unknown>;

      expect(Object.keys(parsed).sort()).toEqual(
        ["conversationId", "expiresAt", "lastActive", "token"].sort(),
      );
      expect(parsed).not.toHaveProperty("tenant_id");
      expect(parsed).not.toHaveProperty("tenantId");
      expect(parsed).not.toHaveProperty("name");
      expect(parsed).not.toHaveProperty("email");
      expect(parsed).not.toHaveProperty("phone");
      expect(parsed).not.toHaveProperty("messages");
      expect(parsed).not.toHaveProperty("message");
    });
  });

  describe("touchResumeRecord", () => {
    it("updates lastActive (and conversationId, when newly known) after a successful turn", () => {
      writeResumeRecord(record({ conversationId: null, lastActive: "2026-07-20T12:00:00.000Z" }));

      const now = new Date("2026-07-20T12:05:00.000Z");
      touchResumeRecord("conv-new", now);

      const result = readResumeRecord(now);
      expect(result?.conversationId).toBe("conv-new");
      expect(result?.lastActive).toBe(now.toISOString());
    });

    it("is a no-op when there is no existing record (never fabricates one)", () => {
      const now = new Date("2026-07-20T12:05:00.000Z");
      touchResumeRecord("conv-new", now);

      expect(sessionStorage.getItem(RESUME_KEY)).toBeNull();
    });
  });

  describe("clearResumeRecord", () => {
    it("removes the key (used on RESUME_REJECTED, decision 7)", () => {
      writeResumeRecord(record());
      expect(sessionStorage.getItem(RESUME_KEY)).not.toBeNull();

      clearResumeRecord();

      expect(sessionStorage.getItem(RESUME_KEY)).toBeNull();
    });

    it("is a safe no-op when no record exists", () => {
      expect(() => clearResumeRecord()).not.toThrow();
    });
  });
});
