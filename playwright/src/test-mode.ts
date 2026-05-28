/**
 * TypeScript wrappers for the viur-testing bootstrap endpoints.
 *
 * Mirrors the Python `viur.testing.require_test_mode` / `finish` helpers
 * over plain HTTP. These two calls are the ONLY ones in the suite that
 * may run without the `X-Viur-Test-Token` header — they live on the
 * server-side bootstrap allow-list. Every other request from Playwright
 * (browser navigation, fetch/XHR, APIRequestContext) MUST carry the
 * token; the fixtures in `fixtures.ts` enforce that.
 */

import { createHash } from "node:crypto"

import { request as playwrightRequest, type APIRequestContext } from "@playwright/test"

export const TOKEN_HEADER = "X-Viur-Test-Token"

export interface ServerStatus {
  test_mode: true
  is_dev_server: true
  database: string
  namespace: string | null
  project_id: string
  token: string
  token_hash: string
  version: string
  /** Project-specific fields merged in by status hooks registered via
   *  `viur.testing.register_status_hook(...)`. The package keeps the
   *  type open so each project can declare its own extension via
   *  module augmentation if it wants strictness. */
  [extra: string]: unknown
}

export interface RequireTestModeOptions {
  /** Base URL of the running ViUR backend, e.g. http://localhost:8080. */
  backendUrl: string
  /** Expected database name — preflight fails if the server reports otherwise. */
  expectedDatabase?: string
  /**
   * Expected Datastore namespace. Pass a string for a named namespace,
   * `null` (or the empty string `""`) to assert the server is on the
   * default namespace, or omit the field to skip the namespace check
   * entirely. The empty-string normalisation mirrors the server-side
   * convention from `VIUR_TESTING_NAMESPACE` so callers can pass
   * `process.env.E2E_TEST_NAMESPACE` straight through.
   */
  expectedNamespace?: string | null
  /**
   * Optional GCP project ID assertion. When set, the server's
   * `project_id` must match — useful in CI where the dev server is
   * pinned to a specific project. Mirrors Python's
   * `require_test_mode(expected_project_id=...)`.
   */
  expectedProjectId?: string
}

/**
 * Preflight check: confirm the server is in test mode and grab the
 * session token. Throws if any of the bilateral handshake invariants
 * fails — see the body for the full check list. Mirrors Python's
 * `viur.testing.require_test_mode` so the JS-side and the Python-side
 * runners enforce the same contract.
 *
 * Uses a fresh APIRequestContext (no shared cookies, no extra headers)
 * because the bootstrap call must run without the token header.
 */
export async function requireTestMode(opts: RequireTestModeOptions): Promise<ServerStatus> {
  const ctx = await playwrightRequest.newContext({ baseURL: opts.backendUrl })
  try {
    const resp = await ctx.post("/json/_test/config/status")
    if (!resp.ok()) {
      throw new Error(
        `viur-testing preflight failed: POST /json/_test/config/status returned ` +
          `${resp.status()} ${resp.statusText()}. Is the backend running with ` +
          `VIUR_TESTING_ENABLE=1 and is viur-testing wired into main.py?`,
      )
    }
    const status = (await resp.json()) as ServerStatus

    if (status.test_mode !== true) {
      throw new Error(
        `viur-testing preflight failed: server reports test_mode=` +
          `${JSON.stringify(status.test_mode)}; refusing to run tests against ` +
          `a non-test instance.`,
      )
    }
    // Hard-stop if the server is somehow not the local dev server.
    // The TypeHint claims ``is_dev_server: true`` but only a runtime
    // check actually enforces it — Python's runner has the same line.
    if (status.is_dev_server !== true) {
      throw new Error(
        `viur-testing preflight failed: server reports is_dev_server=` +
          `${JSON.stringify(status.is_dev_server)}; refusing to run tests against ` +
          `anything that is not a local dev server.`,
      )
    }
    if (opts.expectedDatabase && status.database !== opts.expectedDatabase) {
      throw new Error(
        `viur-testing preflight failed: server is wired to database=` +
          `${JSON.stringify(status.database)} but tests expect ` +
          `${JSON.stringify(opts.expectedDatabase)}`,
      )
    }
    // Use `in` (not truthiness) so callers can pass `null` to assert
    // the server is on the default namespace. Empty string is
    // normalised to null up-front — matches the server-side convention
    // from VIUR_TESTING_NAMESPACE.
    if ("expectedNamespace" in opts) {
      const expected = opts.expectedNamespace === "" ? null : opts.expectedNamespace
      if (status.namespace !== expected) {
        throw new Error(
          `viur-testing preflight failed: server is wired to namespace=` +
            `${JSON.stringify(status.namespace)} but tests expect ` +
            `${JSON.stringify(expected)}`,
        )
      }
    }
    if (opts.expectedProjectId !== undefined && status.project_id !== opts.expectedProjectId) {
      throw new Error(
        `viur-testing preflight failed: server reports project_id=` +
          `${JSON.stringify(status.project_id)} but tests expect ` +
          `${JSON.stringify(opts.expectedProjectId)}`,
      )
    }
    if (typeof status.token !== "string" || status.token.length === 0) {
      throw new Error(
        `viur-testing preflight failed: server response is missing a ` +
          `non-empty 'token' string.`,
      )
    }
    // Cryptographic integrity check: the server hashes the issued
    // token and sends both the token and the hash. If a man-in-the-
    // middle (or a bug) swaps the token, the hash will not match.
    // Python's runner has the same line — without it the JS-side
    // bilateral guarantee is weaker than the Python one.
    const expectedHash = createHash("sha256").update(status.token, "utf8").digest("hex")
    if (status.token_hash !== expectedHash) {
      throw new Error(
        `viur-testing preflight failed: server's token_hash does not match ` +
          `the sha256 of the returned token — the response may have been ` +
          `tampered with or the server is on a different version.`,
      )
    }
    return status
  } finally {
    await ctx.dispose()
  }
}

/**
 * Release the session token at the end of the test run. The server
 * stays in test mode — the next `requireTestMode` call will issue a
 * fresh token.
 *
 * The finish endpoint is on the bootstrap allow-list and therefore
 * accepts the call without a token header. We send the header
 * nonetheless so that the JS-side call shape matches the Python
 * `viur.testing.finish` (which always sends it) — protects against a
 * future allow-list narrowing on the server silently breaking
 * teardown only on the JS side.
 */
export async function finishTestMode(opts: { backendUrl: string; token: string }): Promise<void> {
  const ctx = await playwrightRequest.newContext({
    baseURL: opts.backendUrl,
    extraHTTPHeaders: { [TOKEN_HEADER]: opts.token },
  })
  try {
    const resp = await ctx.post("/json/_test/config/finish")
    if (!resp.ok()) {
      throw new Error(
        `viur-testing teardown failed: POST /json/_test/config/finish returned ` +
          `${resp.status()} ${resp.statusText()}`,
      )
    }
  } finally {
    await ctx.dispose()
  }
}

/**
 * Build an APIRequestContext that always carries the test token. Use
 * this for any direct backend HTTP calls a test makes outside of the
 * browser (e.g. fixture helpers, seeding).
 */
export async function authenticatedApi(opts: {
  backendUrl: string
  token: string
}): Promise<APIRequestContext> {
  return playwrightRequest.newContext({
    baseURL: opts.backendUrl,
    extraHTTPHeaders: { [TOKEN_HEADER]: opts.token },
  })
}
