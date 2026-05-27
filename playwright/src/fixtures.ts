/**
 * Custom Playwright `test` extension that injects the viur-testing
 * token header into EVERY request the suite makes.
 *
 * Two layers:
 *
 * 1. `context` — the browser context all `page.goto` / fetch / XHR
 *    calls from inside the page flow through. We override the default
 *    `context` fixture so every page in the suite is born with
 *    `extraHTTPHeaders: { 'X-Viur-Test-Token': <token> }`.
 *
 * 2. `backendApi` — Playwright's APIRequestContext for direct HTTP calls
 *    from the test code itself. Same treatment.
 *
 * The token is provisioned once in `globalSetup` (see
 * `createGlobalSetup`), persisted to disk under `.auth/token.json`,
 * and read back here. The token-header rule is non-negotiable: any
 * request without the header is rejected with 403 by viur-testing's
 * TokenValidator (only the `/json/_test/config/{status,finish}`
 * bootstrap endpoints are exempt, and those run inside `test-mode.ts`
 * with their own dedicated contexts).
 */

import { test as base, expect, type APIRequestContext, type BrowserContext } from "@playwright/test"
import { readFileSync } from "node:fs"
import { resolve } from "node:path"

import { TOKEN_HEADER, authenticatedApi, type ServerStatus } from "./test-mode.js"

const TOKEN_FILE = resolve(process.cwd(), ".auth", "token.json")

function loadServerStatus(): ServerStatus {
  try {
    return JSON.parse(readFileSync(TOKEN_FILE, "utf8")) as ServerStatus
  } catch (err) {
    throw new Error(
      `Could not read viur-testing session info from ${TOKEN_FILE}. ` +
        `Did globalSetup run? Original error: ${(err as Error).message}`,
    )
  }
}

export interface TestModeFixtures {
  /** Full server status returned by `/json/_test/config/status`. */
  serverStatus: ServerStatus
  /** Direct backend APIRequestContext that already carries the token header. */
  backendApi: APIRequestContext
}

export const test = base.extend<TestModeFixtures>({
  // Override the built-in `context` fixture so every page gets the
  // token header on every request automatically. Pages spawned via
  // `await context.newPage()` and via the standard `page` fixture
  // both inherit this.
  context: async ({ browser }, use) => {
    const status = loadServerStatus()
    const ctx: BrowserContext = await browser.newContext({
      extraHTTPHeaders: { [TOKEN_HEADER]: status.token },
    })
    await use(ctx)
    await ctx.close()
  },

  serverStatus: async ({}, use) => {
    await use(loadServerStatus())
  },

  backendApi: async ({}, use) => {
    const status = loadServerStatus()
    const backendUrl = process.env.E2E_BACKEND_URL ?? "http://localhost:8080"
    const ctx = await authenticatedApi({ backendUrl, token: status.token })
    await use(ctx)
    await ctx.dispose()
  },
})

export { expect }
