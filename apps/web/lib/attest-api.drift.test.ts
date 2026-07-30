import { readFileSync } from "node:fs";
import { join } from "node:path";

/**
 * Every path this app requests must be a path the API serves.
 *
 * `attest-api.ts` builds request paths as template literals. A typo, a renamed
 * route, or a segment dropped during a refactor type-checks perfectly and fails
 * only at runtime — as a 404 the user sees as "something went wrong", on
 * whichever page happens to call it. Nothing in the type system connects a
 * string here to a route over there.
 *
 * So the literals are extracted from the source and matched against the paths in
 * the OpenAPI document the API generates about itself. Reading the source rather
 * than calling the functions is deliberate: calling them would prove only the
 * paths a test happened to exercise, while a route left behind by a rename is
 * precisely the one no test calls.
 */
const source = readFileSync(join(process.cwd(), "lib", "attest-api.ts"), "utf8");
const spec = JSON.parse(
  readFileSync(join(process.cwd(), "..", "..", "packages", "contracts", "openapi.json"), "utf8"),
) as { paths: Record<string, unknown> };

const API_PREFIX = "/api/v1";

/**
 * The base each path helper builds, e.g. `/workspaces/{id}/documents`.
 *
 * Both helpers take an optional second id and append it when given, so the call
 * site's argument count is what decides whether the path gains a segment.
 */
function helperBases(): Map<string, string> {
  const bases = new Map<string, string>();
  for (const [, name, base] of source.matchAll(
    /function (documentsPath|conversationsPath)\([^)]*\)[^{]*\{\s*const base = `([^`]+)`/g,
  )) {
    bases.set(name, base);
  }
  return bases;
}

/** Path template literals, with the helper calls expanded. */
function requestPaths(): string[] {
  const bases = helperBases();
  expect(bases.size).toBe(2);

  const found = new Set<string>();
  for (const [, literal] of source.matchAll(/^\s*path: [`"]([^`"]+)[`"],?$/gm)) {
    const resolved = literal.replace(
      /\$\{(documentsPath|conversationsPath)\(([^)]*)\)\}/g,
      (_match, name: string, args: string) => {
        const base = bases.get(name);
        if (base === undefined) {
          throw new Error(`unknown path helper ${name}`);
        }
        // Two arguments means the optional id was supplied, so the helper
        // appends a segment; one argument leaves the base as it is.
        return args.split(",").length > 1 ? `${base}/\${id}` : base;
      },
    );
    found.add(resolved);
  }
  return [...found].sort();
}

/**
 * Collapse interpolations to the `{param}` form OpenAPI uses.
 *
 * A `${query}` suffix is dropped first: a query string is not part of the path
 * and would otherwise turn `/documents?status=x` into a route nothing serves.
 */
function toTemplate(path: string): string {
  return path.replace(/\$\{query\}/g, "").replace(/\$\{[^}]*\}/g, "{param}");
}

const apiTemplates = new Set(
  Object.keys(spec.paths)
    .filter((path) => path.startsWith(API_PREFIX))
    .map((path) => path.slice(API_PREFIX.length).replace(/\{[^}]+\}/g, "{param}")),
);

describe("request path mirror", () => {
  it("finds the paths in the source at all", () => {
    // A guard on the extraction itself: if the regex stopped matching, every
    // assertion below would pass over an empty set and prove nothing.
    const paths = requestPaths();

    expect(paths.length).toBeGreaterThan(15);
    expect(paths.some((path) => path.includes("/auth/login"))).toBe(true);
    expect(paths.some((path) => path.includes("/citations/resolve"))).toBe(true);
  });

  it("requests only paths the API serves", () => {
    const unknown = requestPaths()
      .map(toTemplate)
      .filter((path) => !apiTemplates.has(path));

    expect(unknown).toEqual([]);
  });

  it("would catch a renamed route", () => {
    // The guard proving the guard, since every real path passes above.
    expect(apiTemplates.has("/workspaces/{param}/citations/resolve")).toBe(true);
    expect(apiTemplates.has("/workspaces/{param}/citations/resolved")).toBe(false);
  });

  it("covers the streaming route the relay reaches directly", () => {
    // Built in the route handler rather than here, and so invisible to the
    // extraction above — but it is a path this app depends on all the same.
    expect(apiTemplates.has("/workspaces/{param}/conversations/{param}/messages/stream")).toBe(
      true,
    );
  });
});
