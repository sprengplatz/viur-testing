/**
 * Factory for the Playwright `globalSetup` hook.
 *
 * Builds the standard viur-testing preflight: assert no spec imports
 * `@playwright/test` directly, POST `/json/_test/config/status` to
 * confirm test mode and grab the token, write the session payload to
 * `.auth/token.json` so the fixtures can read it.
 *
 *     // playwright.config.ts
 *     import { createGlobalSetup } from "@spltz/viur-testing"
 *
 *     export default defineConfig({
 *       globalSetup: createGlobalSetup(),
 *       …
 *     })
 *
 * Configuration via env vars (override-able per process):
 *   - E2E_BACKEND_URL       default: http://localhost:8080
 *   - E2E_TEST_DATABASE     default: viur-tests
 *   - E2E_TEST_NAMESPACE    unset = skip namespace check;
 *                           "" = expect default namespace;
 *                           non-empty = expect exact namespace
 *   - E2E_TEST_PROJECT_ID   unset = skip project_id check;
 *                           non-empty = assert server's project_id
 *                           matches exactly (CI hardening)
 */

import { mkdirSync, writeFileSync } from "node:fs"
import { dirname, resolve } from "node:path"

import { assertNoDirectPlaywrightImports } from "./forbidden-imports.js"
import { requireTestMode } from "./test-mode.js"
import { tokenFilePath } from "./token-storage.js"

export interface GlobalSetupOptions {
  /** Directory containing the spec files. Default: `<cwd>/tests`. */
  testsDir?: string
}

export function createGlobalSetup(opts: GlobalSetupOptions = {}): () => Promise<void> {
  const testsDir = opts.testsDir ?? resolve(process.cwd(), "tests")

  return async function globalSetup(): Promise<void> {
    const tokenFile = tokenFilePath()
    // Hard guard FIRST — fail fast if any spec imports @playwright/test
    // directly. Runs before the preflight so an offline backend cannot
    // mask a broken spec.
    assertNoDirectPlaywrightImports(testsDir)

    const backendUrl = process.env.E2E_BACKEND_URL ?? "http://localhost:8080"
    const expectedDatabase = process.env.E2E_TEST_DATABASE ?? "viur-tests"
    const namespaceRaw = process.env.E2E_TEST_NAMESPACE
    const projectIdRaw = process.env.E2E_TEST_PROJECT_ID

    const status = await requireTestMode({
      backendUrl,
      expectedDatabase,
      // ``requireTestMode`` normalises empty string → null itself; we
      // just decide here whether the field is present at all so the
      // ``"expectedNamespace" in opts`` gate inside the runner triggers.
      ...(namespaceRaw !== undefined ? { expectedNamespace: namespaceRaw } : {}),
      ...(projectIdRaw ? { expectedProjectId: projectIdRaw } : {}),
    })

    mkdirSync(dirname(tokenFile), { recursive: true })
    writeFileSync(tokenFile, JSON.stringify(status, null, 2), "utf8")

    process.env.E2E_TEST_TOKEN = status.token
    process.env.E2E_TEST_DATABASE = status.database

    const namespaceLabel = status.namespace ?? "(default)"
    console.log(
      `[viur-testing] preflight OK — database=${status.database} ` +
        `namespace=${namespaceLabel} project=${status.project_id} ` +
        `version=${status.version}`,
    )
  }
}

/**
 * Default-export instance for plug-and-play wiring.
 *
 * Lets host projects point Playwright at this module directly:
 *
 *     // playwright.config.ts
 *     globalSetup: "@spltz/viur-testing/global-setup",
 *
 * The default options resolve `tests/` and `.auth/token.json`
 * relative to `process.cwd()`, which is the playwright config dir
 * when playwright loads this module — exactly what most projects
 * want. To customise, drop a thin wrapper of your own pointing at
 * `createGlobalSetup({...})` with explicit options.
 */
export default createGlobalSetup()
