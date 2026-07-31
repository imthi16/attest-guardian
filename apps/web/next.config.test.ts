import { afterEach, describe, expect, it, vi } from "vitest";

import type { NextConfig } from "next";

/**
 * The CSP is a security control that varies by environment, which is exactly
 * the kind of thing that is easy to relax for a development convenience and
 * then ship. React's dev build needs `eval()` to rebuild stack frames across
 * the server/client boundary; production React never calls it. So the
 * allowance exists in `next dev` and must not exist in a build.
 *
 * `NODE_ENV` is read when the config module is evaluated, so each case resets
 * the module registry and re-imports rather than mutating a cached value.
 */
async function contentSecurityPolicy(nodeEnv: string): Promise<string> {
  vi.stubEnv("NODE_ENV", nodeEnv);
  vi.resetModules();
  const config: NextConfig = (await import("./next.config")).default;
  const rules = await config.headers!();
  const header = rules[0].headers.find((entry) => entry.key === "Content-Security-Policy");
  expect(header).toBeDefined();
  return header!.value;
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe("web content security policy", () => {
  it("does not permit eval in a production build", async () => {
    expect(await contentSecurityPolicy("production")).not.toContain("'unsafe-eval'");
  });

  it("permits eval under next dev, where React requires it", async () => {
    expect(await contentSecurityPolicy("development")).toContain("'unsafe-eval'");
  });

  it("keeps the rest of the policy identical in both environments", async () => {
    const development = (await contentSecurityPolicy("development")).replace(" 'unsafe-eval'", "");
    expect(development).toBe(await contentSecurityPolicy("production"));
  });

  it("never relaxes the directives that are not about scripts", async () => {
    const production = await contentSecurityPolicy("production");
    expect(production).toContain("object-src 'none'");
    expect(production).toContain("frame-ancestors 'none'");
    expect(production).toContain("form-action 'self'");
  });
});
