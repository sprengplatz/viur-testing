/**
 * Factory for the Playwright `globalTeardown` hook.
 *
 * Calls `/json/_test/config/finish` to release the session token in
 * the test database, then removes `.auth/token.json` so a later run
 * cannot accidentally re-use a now-invalid token.
 *
 *     import { createGlobalTeardown } from "@spltz/viur-testing"
 *
 *     export default defineConfig({
 *       globalTeardown: createGlobalTeardown(),
 *       …
 *     })
 */

import { existsSync, readFileSync, unlinkSync } from "node:fs"

import { finishTestMode, type ServerStatus } from "./test-mode.js"
import { tokenFilePath } from "./token-storage.js"

export interface GlobalTeardownOptions {
  // intentionally empty — kept for forward-compat in case the
  // teardown ever needs configuration. The token file location is
  // hard-coded via :func:`tokenFilePath` so it cannot drift away
  // from what the fixtures/test-module helpers read back.
}

export function createGlobalTeardown(_opts: GlobalTeardownOptions = {}): () => Promise<void> {
  return async function globalTeardown(): Promise<void> {
    const tokenFile = tokenFilePath()
    if (!existsSync(tokenFile)) {
      return
    }
    const status = JSON.parse(readFileSync(tokenFile, "utf8")) as ServerStatus
    const backendUrl = process.env.E2E_BACKEND_URL ?? "http://localhost:8080"
    try {
      await finishTestMode({ backendUrl, token: status.token })
    } catch (err) {
      console.warn(`[viur-testing] teardown could not finish session: ${(err as Error).message}`)
    } finally {
      unlinkSync(tokenFile)
    }
  }
}

/**
 * Default-export instance for plug-and-play wiring.
 *
 *     // playwright.config.ts
 *     globalTeardown: "@spltz/viur-testing/global-teardown",
 */
export default createGlobalTeardown()
