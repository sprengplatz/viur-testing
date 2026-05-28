/**
 * Helpers for calling project-specific test modules under /json/_test/.
 *
 * Convention: every spec file has a matching backend module mounted
 * under /json/_test/<specName>/ via `viur.testing.register_test_submodule`.
 * Each module exposes `setup` and `teardown` POST endpoints.
 *
 *   import { test, callTestModule } from "@spltz/viur-testing"
 *
 *   test.beforeAll(async () => {
 *     const { credentials } = await callTestModule("userLogin", "setup")
 *     creds = credentials
 *   })
 *   test.afterAll(() => callTestModule("userLogin", "teardown"))
 *
 * In **Test Mode** `callTestModule` builds a fresh APIRequestContext
 * with the session token header attached, so the call passes
 * viur-testing's TokenValidator. It reads the token from
 * `.auth/token.json` which `globalSetup` wrote.
 *
 * In **Guarded Mode** the backend has no ``/_test/`` endpoints, so a
 * call would 404. Instead of failing the test, ``callTestModule``
 * detects guarded mode via the ``VIUR_TESTING_MODE`` env var and
 * calls ``test.skip(...)`` — the consuming test (or its
 * ``beforeAll`` hook) is marked **skipped**, not **failed**, with a
 * clear reason. Specs that don't touch test modules run normally.
 */

import { readFileSync } from "node:fs"

// Importing `test` directly from @playwright/test is the only place
// in this package where that is necessary — it lets ``callTestModule``
// trigger a runtime skip from inside a regular test/hook callback.
// User specs MUST go through ``@spltz/viur-testing``'s re-export
// instead, which the ``assertNoDirectPlaywrightImports`` guard
// enforces.
// eslint-disable-next-line no-restricted-imports
import { test, type APIRequestContext } from "@playwright/test"

import { MODE_ENV_VAR } from "./global-setup.js"
import { authenticatedApi, type ServerStatus } from "./test-mode.js"
import { tokenFilePath } from "./token-storage.js"

const SKIP_REASON_GUARDED = "uses _test infrastructure, skipped in guarded mode"

/**
 * Cookie payload shape extracted from ``APIRequestContext.storageState()``.
 *
 * Derived from Playwright's own return type rather than hand-typed
 * so the fields stay in sync if Playwright's Cookie shape evolves —
 * the previous hand-written subset dropped ``sameSite``/``secure``/
 * ``httpOnly``/``expires``, which broke flows where the backend set
 * cookies with ``SameSite=Lax`` and the test then handed them off to
 * a browser context via ``addCookies(...)``.
 */
type StorageCookie = Awaited<
  ReturnType<APIRequestContext["storageState"]>
>["cookies"][number]

function loadStatus(): ServerStatus {
  const path = tokenFilePath()
  try {
    return JSON.parse(readFileSync(path, "utf8")) as ServerStatus
  } catch (err) {
    throw new Error(
      `Cannot read ${path}. Did globalSetup run? ` +
        `Original error: ${(err as Error).message}`,
    )
  }
}

export interface TestModuleResult<T> {
  body: T
  /** Cookies in Playwright's `BrowserContext.addCookies(...)` shape,
   *  captured from the response's `Set-Cookie` headers via the
   *  APIRequestContext's storage state. Useful when a setup endpoint
   *  forges a session and the spec wants to hand the resulting cookie
   *  to the browser. Carries the full Playwright Cookie shape
   *  (``sameSite``, ``secure``, ``httpOnly``, ``expires``) so a
   *  ``SameSite=Lax`` cookie survives the handoff intact. */
  cookies: StorageCookie[]
}

/**
 * POST `/json/_test/<spec>/<action>` and return the parsed JSON body.
 *
 * The `spec` name is lower-cased before being put on the wire because
 * viur-core lower-cases every URL path segment at routing time. Pass
 * `"userLogin"` or `"userlogin"` — both work.
 */
export async function callTestModule<T = unknown>(
  spec: string,
  action: string,
): Promise<T> {
  return (await callTestModuleRaw<T>(spec, action)).body
}

/**
 * Like {@link callTestModule}, but also returns the cookies the backend
 * set on the response. Use this for test-fixture endpoints that forge a
 * session server-side — the caller transplants the cookies into the
 * browser context so the app boots already authenticated.
 */
export async function callTestModuleRaw<T = unknown>(
  spec: string,
  action: string,
): Promise<TestModuleResult<T>> {
  if (process.env[MODE_ENV_VAR] === "guarded") {
    // ``test.skip()`` from inside a hook or test body throws an
    // internal "skipped" control signal. Playwright catches it,
    // marks the consuming test (or all tests in the describe, if
    // called from a ``beforeAll``) as skipped, and continues.
    test.skip(true, SKIP_REASON_GUARDED)
    // Unreachable — test.skip throws — but the return type wants
    // a value, so satisfy it. (The TS narrowing of test.skip is
    // ``never``, but ``test.skip(condition, reason)`` returns
    // ``void`` in the typing.)
    throw new Error(SKIP_REASON_GUARDED)
  }
  const status = loadStatus()
  const backendUrl = process.env.E2E_BACKEND_URL ?? "http://localhost:8080"
  const api = await authenticatedApi({ backendUrl, token: status.token })
  const path = `/json/_test/${spec.toLowerCase()}/${action}`
  try {
    const resp = await api.post(path)
    if (!resp.ok()) {
      const body = await resp.text()
      throw new Error(
        `Test-module call ${path} failed with ` +
          `${resp.status()} ${resp.statusText()}: ${body.slice(0, 200)}`,
      )
    }
    const body = (await resp.json()) as T
    const state = await api.storageState()
    // Spread to detach from the storage-state internal array.
    const cookies: StorageCookie[] = state.cookies.map((c) => ({ ...c }))
    return { body, cookies }
  } finally {
    await api.dispose()
  }
}
