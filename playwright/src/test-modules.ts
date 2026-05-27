/**
 * Helpers for calling project-specific test modules under /json/_test/.
 *
 * Convention: every spec file has a matching backend module mounted
 * under /json/_test/<specName>/ via `viur.testing.register_test_submodule`.
 * Each module exposes `setup` and `teardown` POST endpoints.
 *
 *   import { callTestModule } from "@spltz/viur-testing"
 *
 *   test.beforeAll(async () => {
 *     const { credentials } = await callTestModule("userLogin", "setup")
 *     creds = credentials
 *   })
 *   test.afterAll(() => callTestModule("userLogin", "teardown"))
 *
 * `callTestModule` builds a fresh APIRequestContext with the session
 * token header attached, so the call passes viur-testing's
 * TokenValidator. It reads the token from `.auth/token.json` which
 * `globalSetup` wrote.
 */

import { readFileSync } from "node:fs"
import { resolve } from "node:path"

import { authenticatedApi, type ServerStatus } from "./test-mode.js"

const TOKEN_FILE = resolve(process.cwd(), ".auth", "token.json")

function loadStatus(): ServerStatus {
  try {
    return JSON.parse(readFileSync(TOKEN_FILE, "utf8")) as ServerStatus
  } catch (err) {
    throw new Error(
      `Cannot read ${TOKEN_FILE}. Did globalSetup run? ` +
        `Original error: ${(err as Error).message}`,
    )
  }
}

export interface TestModuleResult<T> {
  body: T
  /** Cookies in Playwright's `BrowserContext.addCookies(...)` shape, captured
   *  from the response's `Set-Cookie` headers via the APIRequestContext's
   *  storage state. Useful when a setup endpoint forges a session and the
   *  spec wants to hand the resulting cookie to the browser. */
  cookies: { name: string; value: string; domain: string; path: string }[]
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
    const cookies = state.cookies.map((c) => ({
      name: c.name,
      value: c.value,
      domain: c.domain,
      path: c.path,
    }))
    return { body, cookies }
  } finally {
    await api.dispose()
  }
}
