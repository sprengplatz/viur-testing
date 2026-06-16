/**
 * Custom Playwright `test` extension that sets the viur-testing token
 * cookie on the browsing context — in **Test Mode**.
 *
 * Two layers:
 *
 * 1. `context` — the browser context all `page.goto` / fetch / XHR
 *    calls from inside the page flow through. In Test Mode the
 *    ``viur-test-token`` cookie is set on it once, so it rides along on
 *    every request including hard navigations; in Guarded Mode it is a
 *    vanilla browser context (no cookie — Playwright acts as a normal
 *    client).
 *
 * 2. `backendApi` — APIRequestContext for direct HTTP calls from the
 *    test code itself. Test-mode only — in Guarded Mode the
 *    consuming test is auto-skipped because the `_test/`
 *    infrastructure that backs it is not available.
 *
 * In Test Mode the token is provisioned once in `globalSetup` (see
 * `createGlobalSetup`), persisted to disk under `.auth/token.json`,
 * and read back here once per worker. In Guarded Mode the worker
 * fixture returns `null` and every fixture that needs the token
 * calls ``testInfo.skip(...)`` so the test counts as **skipped**,
 * not **failed**.
 */

import { test as base, expect, type APIRequestContext, type BrowserContext } from "@playwright/test"
import { readFileSync } from "node:fs"

import { MODE_ENV_VAR } from "./global-setup.js"
import { TOKEN_COOKIE, authenticatedApi, type ServerStatus } from "./test-mode.js"
import { tokenFilePath } from "./token-storage.js"

function loadServerStatus(): ServerStatus {
  const path = tokenFilePath()
  try {
    return JSON.parse(readFileSync(path, "utf8")) as ServerStatus
  } catch (err) {
    throw new Error(
      `Could not read viur-testing session info from ${path}. ` +
        `Did globalSetup run? Original error: ${(err as Error).message}`,
    )
  }
}

function isGuardedMode(): boolean {
  return process.env[MODE_ENV_VAR] === "guarded"
}

const SKIP_REASON_GUARDED = "uses _test infrastructure, skipped in guarded mode"

export interface TestModeFixtures {
  /** Full server status returned by `/json/_test/config/status`.
   *  Only available in test mode; the fixture auto-skips the test
   *  in guarded mode. */
  serverStatus: ServerStatus
  /** Direct backend APIRequestContext that already carries the token
   *  header. Only available in test mode; the fixture auto-skips
   *  the test in guarded mode. */
  backendApi: APIRequestContext
}

interface TestModeWorkerFixtures {
  /**
   * Worker-scoped cache of the server status JSON, populated by
   * reading ``.auth/token.json`` exactly once per worker process.
   * Resolves to ``null`` in guarded mode — the test-scoped fixtures
   * (``serverStatus``/``backendApi``) check the null and skip the
   * consuming test before ever hitting the network.
   *
   * Underscore-prefixed and not re-exported as part of the public
   * surface — callers go through ``serverStatus``/``backendApi``/
   * ``context`` instead.
   */
  _viurTestingStatus: ServerStatus | null
}

export const test = base.extend<TestModeFixtures, TestModeWorkerFixtures>({
  _viurTestingStatus: [
    async ({}, use) => {
      if (isGuardedMode()) {
        await use(null)
      } else {
        await use(loadServerStatus())
      }
    },
    { scope: "worker" },
  ],

  // Override the built-in `context` fixture. In test mode the token is
  // set once as a cookie on the context, so it rides along on every
  // request — fetch/XHR AND hard navigations — exactly like a manually
  // armed browser. In guarded mode the context is a vanilla browser
  // context so Playwright behaves like a normal client against the live
  // backend.
  context: async ({ browser, baseURL, _viurTestingStatus }, use) => {
    const ctx: BrowserContext = await browser.newContext()
    if (_viurTestingStatus !== null) {
      const origin = new URL(
        baseURL ?? process.env.E2E_BACKEND_URL ?? "http://localhost:8080",
      ).origin
      await ctx.addCookies([
        {
          name: TOKEN_COOKIE,
          value: _viurTestingStatus.token,
          url: origin,
          sameSite: "Strict",
          httpOnly: true,
        },
      ])
    }
    await use(ctx)
    await ctx.close()
  },

  serverStatus: async ({ _viurTestingStatus }, use, testInfo) => {
    if (_viurTestingStatus === null) {
      testInfo.skip(true, SKIP_REASON_GUARDED)
      // testInfo.skip throws an internal "test skipped" control
      // signal; the line below never runs, but the typechecker
      // wants a return.
      return
    }
    await use(_viurTestingStatus)
  },

  backendApi: async ({ _viurTestingStatus }, use, testInfo) => {
    if (_viurTestingStatus === null) {
      testInfo.skip(true, SKIP_REASON_GUARDED)
      return
    }
    const backendUrl = process.env.E2E_BACKEND_URL ?? "http://localhost:8080"
    const ctx = await authenticatedApi({
      backendUrl, token: _viurTestingStatus.token,
    })
    await use(ctx)
    await ctx.dispose()
  },
})

export { expect }
