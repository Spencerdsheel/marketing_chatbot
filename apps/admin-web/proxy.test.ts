import { describe, expect, it } from "vitest";
import jwt from "jsonwebtoken";
import { NextRequest } from "next/server";
// NOTE: the installed Next.js version (16.2.10) still exports this testing
// helper under its pre-rename name `unstable_doesMiddlewareMatch` even
// though the file-convention itself is `proxy.ts`/`proxy()` -- verified by
// inspecting the actual module exports (docs describe a newer name that
// isn't present in this version). Using the real export, not the doc name.
import { unstable_doesMiddlewareMatch as unstable_doesProxyMatch } from "next/experimental/testing/server";
import { proxy, config } from "@/proxy";

const SECRET = process.env.JWT_SECRET as string;

function requestTo(path: string, cookieValue?: string): NextRequest {
  const req = new NextRequest(new URL(path, "http://localhost:3000"));
  if (cookieValue !== undefined) {
    req.cookies.set("access_token", cookieValue);
  }
  return req;
}

const validToken = jwt.sign(
  { sub: "u1", role: "CLIENT_ADMIN", tenant_id: "t1", project_ids: [] },
  SECRET,
  { algorithm: "HS256", expiresIn: "1h" }
);

describe("proxy (route gate)", () => {
  it("redirects to /login when no cookie is present on a protected route", () => {
    const res = proxy(requestTo("/"));
    expect(res.status).toBe(307);
    expect(res.headers.get("location")).toContain("/login");
  });

  it("redirects to /login when the cookie is invalid/tampered", () => {
    const res = proxy(requestTo("/", "not-a-valid-jwt"));
    expect(res.status).toBe(307);
    expect(res.headers.get("location")).toContain("/login");
  });

  it("passes through when the cookie holds a valid token", () => {
    const res = proxy(requestTo("/", validToken));
    // NextResponse.next() has no redirect status/location.
    expect(res.headers.get("location")).toBeNull();
  });

  it("matcher config excludes /login (never gated, no redirect loop)", () => {
    expect(
      unstable_doesProxyMatch({ config, nextConfig: {}, url: "/login" })
    ).toBe(false);
  });

  it("matcher config includes protected paths", () => {
    expect(unstable_doesProxyMatch({ config, nextConfig: {}, url: "/" })).toBe(
      true
    );
    expect(
      unstable_doesProxyMatch({ config, nextConfig: {}, url: "/leads" })
    ).toBe(true);
  });
});
