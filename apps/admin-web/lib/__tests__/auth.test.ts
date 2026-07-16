import { describe, expect, it } from "vitest";
import jwt from "jsonwebtoken";
import { verifyToken } from "@/lib/auth";

// Matches vitest.setup.ts.
const SECRET = process.env.JWT_SECRET as string;

function signToken(
  payload: Record<string, unknown>,
  opts: jwt.SignOptions = {}
): string {
  return jwt.sign(payload, SECRET, { algorithm: "HS256", ...opts });
}

const validPayload = {
  sub: "user-123",
  role: "CLIENT_ADMIN",
  tenant_id: "tenant-abc",
  project_ids: ["proj-1"],
};

describe("verifyToken", () => {
  it("decodes a valid token into Claims", () => {
    const token = signToken(validPayload, { expiresIn: "1h" });
    const claims = verifyToken(token);
    expect(claims).toEqual({
      subject: "user-123",
      role: "CLIENT_ADMIN",
      tenantId: "tenant-abc",
      projectIds: ["proj-1"],
    });
  });

  it("decodes a PLATFORM_ADMIN token with null tenant_id", () => {
    const token = signToken(
      { sub: "admin-1", role: "PLATFORM_ADMIN", tenant_id: null, project_ids: [] },
      { expiresIn: "1h" }
    );
    const claims = verifyToken(token);
    expect(claims?.tenantId).toBeNull();
    expect(claims?.role).toBe("PLATFORM_ADMIN");
  });

  it("returns null for an expired token", () => {
    const token = signToken(validPayload, { expiresIn: -10 });
    expect(verifyToken(token)).toBeNull();
  });

  it("returns null for a missing token", () => {
    expect(verifyToken(undefined)).toBeNull();
    expect(verifyToken(null)).toBeNull();
    expect(verifyToken("")).toBeNull();
  });

  it("returns null for a malformed/invalid token string", () => {
    expect(verifyToken("not-a-jwt-at-all")).toBeNull();
  });

  it("returns null for a token with a tampered signature", () => {
    const token = signToken(validPayload, { expiresIn: "1h" });
    // Flip a character in the signature segment.
    const parts = token.split(".");
    const tamperedSig =
      parts[2].slice(0, -1) + (parts[2].at(-1) === "a" ? "b" : "a");
    const tampered = `${parts[0]}.${parts[1]}.${tamperedSig}`;
    expect(verifyToken(tampered)).toBeNull();
  });

  it("returns null for a token signed with the wrong secret", () => {
    const token = jwt.sign(validPayload, "a-completely-different-secret-value", {
      algorithm: "HS256",
      expiresIn: "1h",
    });
    expect(verifyToken(token)).toBeNull();
  });

  it("never throws on garbage input", () => {
    expect(() => verifyToken("{}")).not.toThrow();
    expect(() => verifyToken("a.b.c")).not.toThrow();
  });
});
