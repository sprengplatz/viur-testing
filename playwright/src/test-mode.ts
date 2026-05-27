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
   * `null` to assert the server is on the default namespace, or omit
   * the field to skip the namespace check entirely.
   */
  expectedNamespace?: string | null
}

/**
 * Preflight check: confirm the server is in test mode and grab the
 * session token. Throws if the server is not in test mode, points at
 * the wrong database, or the endpoint is unreachable.
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
    if (!status.test_mode) {
      throw new Error("viur-testing preflight failed: server reports test_mode=false")
    }
    if (opts.expectedDatabase && status.database !== opts.expectedDatabase) {
      throw new Error(
        `viur-testing preflight failed: server is wired to database=` +
          `${JSON.stringify(status.database)} but tests expect ` +
          `${JSON.stringify(opts.expectedDatabase)}`,
      )
    }
    // Use `in` (not truthiness) so callers can pass `null` to assert
    // the server is on the default namespace.
    if ("expectedNamespace" in opts && status.namespace !== opts.expectedNamespace) {
      throw new Error(
        `viur-testing preflight failed: server is wired to namespace=` +
          `${JSON.stringify(status.namespace)} but tests expect ` +
          `${JSON.stringify(opts.expectedNamespace)}`,
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
 * The finish endpoint is also on the bootstrap allow-list, so this
 * call does NOT need the token header either.
 */
export async function finishTestMode(opts: { backendUrl: string; token: string }): Promise<void> {
  const ctx = await playwrightRequest.newContext({ baseURL: opts.backendUrl })
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
