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
import { resolve } from "node:path"

import { finishTestMode, type ServerStatus } from "./test-mode.js"

export interface GlobalTeardownOptions {
  /** Path to the token persistence file. Default: `<cwd>/.auth/token.json`. */
  tokenFile?: string
}

export function createGlobalTeardown(opts: GlobalTeardownOptions = {}): () => Promise<void> {
  const tokenFile = opts.tokenFile ?? resolve(process.cwd(), ".auth", "token.json")

  return async function globalTeardown(): Promise<void> {
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
