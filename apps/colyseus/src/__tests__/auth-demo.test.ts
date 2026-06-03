import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Must mock env before importing auth
const originalEnv = process.env;

describe("verifyToken — demo tokens", () => {
  beforeEach(() => {
    process.env = { ...originalEnv, DEV_AUTH_BYPASS: "false" };
  });

  afterEach(() => {
    process.env = originalEnv;
    vi.restoreAllMocks();
  });

  it("accepts a demo token with org_id=demo-public and role=demo", async () => {
    // Dynamically import to pick up mocked env
    const { verifyToken } = await import("../auth");

    const header = Buffer.from(JSON.stringify({ alg: "none", typ: "JWT" })).toString("base64");
    const payload = Buffer.from(
      JSON.stringify({
        sub: "demo-abc123",
        org_id: "demo-public",
        roles: ["demo"],
        email: "demo@selva.town",
        name: "Test Visitor",
      }),
    ).toString("base64");
    const token = `${header}.${payload}.`;

    const result = await verifyToken(token, { name: "Fallback" });
    expect(result.sub).toBe("demo-abc123");
    expect(result.orgId).toBe("demo-public");
    expect(result.roles).toEqual(["demo"]);
    expect(result.name).toBe("Fallback"); // name from options takes precedence
    expect(result.isGuest).toBe(false);
    expect(result.isDemo).toBe(true);
  });

  it("rejects a token without demo role", async () => {
    const { verifyToken } = await import("../auth");

    const header = Buffer.from(JSON.stringify({ alg: "none", typ: "JWT" })).toString("base64");
    const payload = Buffer.from(
      JSON.stringify({
        sub: "user-123",
        org_id: "demo-public",
        roles: ["user"],
      }),
    ).toString("base64");
    const token = `${header}.${payload}.`;

    // This should fall through to JWKS verification which will fail
    // because there's no JANUA_ISSUER_URL configured
    await expect(verifyToken(token)).rejects.toThrow();
  });
});
