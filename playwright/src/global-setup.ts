/**
 * Factory for the Playwright `globalSetup` hook.
 *
 * Auto-detects the run mode from the backend's behaviour:
 *
 *   - ``POST /json/_test/config/status`` returns 200 + a validated
 *     test-mode payload → **Test Mode**: write the session payload
 *     to ``.auth/token.json``, set ``VIUR_TESTING_MODE=test``,
 *     workers pick up the token via the fixtures.
 *   - returns any 4xx → **Guarded Mode**: run an interactive 6-digit
 *     PIN challenge on the terminal. On success, set
 *     ``VIUR_TESTING_MODE=guarded`` and proceed without a token —
 *     specs that use `_test` infrastructure auto-skip; everything
 *     else runs against the live backend exactly as a browser
 *     would. (Folding the whole 4xx range — not just 404 — is
 *     required because ViUR's JSON renderer surfaces unknown
 *     modules as 401.)
 *   - anything else (5xx, timeout, malformed JSON, integrity
 *     failure) → hard error, no fallback. Ambiguous server state
 *     is never silently downgraded to Guarded Mode.
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
 *   - E2E_TEST_DATABASE     default: viur-tests (test mode only)
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
import { detectMode } from "./mode-detect.js"
import { tokenFilePath } from "./token-storage.js"

/**
 * Env-var name that ``globalSetup`` writes after mode detection.
 * Workers inherit ``process.env`` from the main process so the
 * fixtures and ``callTestModule`` can branch on it.
 */
export const MODE_ENV_VAR = "VIUR_TESTING_MODE"

export interface GlobalSetupOptions {
  /** Directory containing the spec files. Default: `<cwd>/tests`. */
  testsDir?: string
  /** Override the backend URL (otherwise read from `E2E_BACKEND_URL`). */
  backendUrl?: string
}

export function createGlobalSetup(opts: GlobalSetupOptions = {}): () => Promise<void> {
  const testsDir = opts.testsDir ?? resolve(process.cwd(), "tests")

  return async function globalSetup(): Promise<void> {
    // Hard guard FIRST — fail fast if any spec imports @playwright/test
    // directly. Runs before the preflight so an offline backend cannot
    // mask a broken spec.
    assertNoDirectPlaywrightImports(testsDir)

    const backendUrl =
      opts.backendUrl ?? process.env.E2E_BACKEND_URL ?? "http://localhost:8080"
    const expectedDatabase = process.env.E2E_TEST_DATABASE ?? "viur-tests"
    const namespaceRaw = process.env.E2E_TEST_NAMESPACE
    const projectIdRaw = process.env.E2E_TEST_PROJECT_ID

    console.log(
      `[viur-testing] probing ${backendUrl}/json/_test/config/status ...`,
    )

    const detected = await detectMode({
      backendUrl,
      expectedDatabase,
      // ``detectMode`` (via ``probeStatusEndpoint``) normalises empty
      // string → null itself; we just decide here whether the field
      // is present at all so the ``"expectedNamespace" in opts`` gate
      // inside the runner triggers.
      ...(namespaceRaw !== undefined ? { expectedNamespace: namespaceRaw } : {}),
      ...(projectIdRaw ? { expectedProjectId: projectIdRaw } : {}),
    })

    if (detected.mode === "test") {
      const { status } = detected
      const tokenFile = tokenFilePath()
      mkdirSync(dirname(tokenFile), { recursive: true })
      writeFileSync(tokenFile, JSON.stringify(status, null, 2), "utf8")

      process.env[MODE_ENV_VAR] = "test"
      process.env.E2E_TEST_TOKEN = status.token
      process.env.E2E_TEST_DATABASE = status.database

      const namespaceLabel = status.namespace ?? "(default)"
      console.log(
        `[viur-testing] test mode — database=${status.database} ` +
          `namespace=${namespaceLabel} project=${status.project_id} ` +
          `version=${status.version}`,
      )
    } else {
      // Guarded mode: no token, no .auth/token.json — fixtures and
      // callTestModule check MODE_ENV_VAR and auto-skip the affected
      // tests. We stash the backend URL so globalTeardown knows
      // there's nothing to call /finish on.
      process.env[MODE_ENV_VAR] = "guarded"
      console.log(
        `[viur-testing] guarded mode — running specs against ${backendUrl}. ` +
          `Specs that depend on _test/ infrastructure will be skipped.`,
      )
    }
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
