/**
 * JWT verification for Colyseus room authentication.
 *
 * Uses the `jose` library for JWKS-based verification.
 * Falls back to accepting any connection when DEV_AUTH_BYPASS is enabled.
 */

import { createRemoteJWKSet, jwtVerify, type JWTPayload } from "jose";
import { createLogger } from "@selva/config/logging";

const logger = createLogger({ service: "colyseus" }).child({ component: "auth" });

const DEV_AUTH_BYPASS = process.env.DEV_AUTH_BYPASS === "true";
const JANUA_ISSUER_URL = process.env.JANUA_ISSUER_URL ?? "";

// Lazily-initialized JWKS function.
let jwks: ReturnType<typeof createRemoteJWKSet> | null = null;

function getJWKS(): ReturnType<typeof createRemoteJWKSet> {
  if (!jwks) {
    const jwksUrl = new URL("/.well-known/jwks.json", JANUA_ISSUER_URL);
    jwks = createRemoteJWKSet(jwksUrl);
  }
  return jwks;
}

export interface AuthResult {
  sub: string;
  orgId: string;
  roles: string[];
  name: string;
  isGuest: boolean;
  isDemo: boolean;
}

/**
 * Verify a JWT token from the client's join options.
 *
 * In dev mode with DEV_AUTH_BYPASS=true, returns a synthetic auth result
 * allowing any connection.
 */
export async function verifyToken(
  token: string | undefined,
  options?: { name?: string },
): Promise<AuthResult> {
  // Check for demo tokens (unsigned JWTs with org_id=demo-public)
  if (token) {
    try {
      const parts = token.split(".");
      if (parts.length >= 2) {
        const payload = JSON.parse(Buffer.from(parts[1], "base64").toString());

        // If not a demo token, require a signature
        const isDemo = payload.org_id === "demo-public" && Array.isArray(payload.roles) && payload.roles.includes("demo");
        if (!isDemo && (!parts[2] || parts[2] === "")) {
          throw new Error("Unsigned JWTs are not allowed for authenticated sessions");
        }

        if (isDemo) {
          return {
            sub: payload.sub ?? "demo-anon",
            orgId: "demo-public",
            roles: ["demo"],
            name: options?.name ?? payload.name ?? "Visitor",
            isGuest: false,
            isDemo: true,
          };
        }
      }
    } catch (err) {
      // Re-throw unsigned JWT rejection — must not be swallowed
      if (err instanceof Error && err.message.includes("Unsigned JWTs")) {
        throw err;
      }
      // Not a demo token — fall through to normal verification
    }
  }

  if (DEV_AUTH_BYPASS) {
    return {
      sub: "dev-user-00000000",
      orgId: "dev-org",
      roles: ["admin", "tactician"],
      name: options?.name ?? "Player",
      isGuest: false,
      isDemo: false,
    };
  }

  if (!token) {
    throw new Error("Missing authentication token");
  }

  try {
    const { payload } = await jwtVerify(token, getJWKS(), {
      issuer: JANUA_ISSUER_URL,
    });

    const roles = (payload as JWTPayload & { roles?: string[] }).roles ?? [];
    const orgId =
      (payload as JWTPayload & { org_id?: string; oid?: string }).org_id ??
      (payload as JWTPayload & { oid?: string }).oid ??
      "unknown";

    return {
      sub: payload.sub ?? "unknown",
      orgId,
      roles,
      name: (payload as JWTPayload & { name?: string }).name ?? options?.name ?? "Player",
      isGuest: roles.includes("guest"),
      isDemo: false,
    };
  } catch (err) {
    logger.warn({ err }, "JWT verification failed");
    throw new Error("Invalid or expired token");
  }
}
