/**
 * Scaffolding logic for `viur-testing-init`.
 *
 * Drops the standard set of e2e-suite files into a target directory.
 * Re-runnable — already-existing files are skipped, never overwritten.
 *
 * The entry point lives in `bin/init.mjs` (a tiny shebang wrapper)
 * so npm can resolve the bin without TS-compiler shebang quirks.
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs"
import { dirname, isAbsolute, join, resolve } from "node:path"

/** Default subdirectory beneath `cwd` where the e2e suite gets scaffolded. */
const DEFAULT_RELATIVE_TARGET = "testing/e2e"

const TEMPLATES: Record<string, string> = {
  "package.json": `{
  "name": "PROJECT-e2e",
  "private": true,
  "version": "0.1.0",
  "description": "End-to-end Playwright tests for PROJECT.",
  "type": "module",
  "scripts": {
    "test": "playwright test",
    "test:headed": "playwright test --headed",
    "test:ui": "playwright test --ui",
    "codegen": "playwright codegen http://localhost:8081/",
    "report": "playwright show-report",
    "install-browsers": "playwright install --with-deps chromium",
    "dev:frontend": "cd ../../sources/app && vite --mode e2e --config ../../testing/e2e/vite.e2e.config.ts --port 8081"
  },
  "devDependencies": {
    "@playwright/test": "^1.49.0",
    "@spltz/viur-testing": "*",
    "@types/node": "^22.10.0",
    "typescript": "^5.6.0"
  }
}
`,

  "tsconfig.json": `{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "esModuleInterop": true,
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "skipLibCheck": true,
    "resolveJsonModule": true,
    "types": ["node", "@playwright/test"]
  },
  "include": ["**/*.ts", "playwright.config.ts"],
  "exclude": ["node_modules", "test-results", "playwright-report"]
}
`,

  "playwright.config.ts": `import { defineConfig, devices } from "@playwright/test"

const FRONTEND_URL = process.env.E2E_FRONTEND_URL ?? "http://localhost:8081/"
const BACKEND_URL = process.env.E2E_BACKEND_URL ?? "http://localhost:8080"

// globalSetup / fixtures pick this up via process.env — set here so a
// single override on the playwright CLI flows everywhere consistently.
process.env.E2E_BACKEND_URL = BACKEND_URL

export default defineConfig({
  testDir: "./tests",
  outputDir: "./test-results",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI
    ? [["github"], ["html", { open: "never" }]]
    : [["list"], ["html", { open: "never" }]],
  globalSetup: "@spltz/viur-testing/global-setup",
  globalTeardown: "@spltz/viur-testing/global-teardown",

  use: {
    baseURL: FRONTEND_URL,
    trace: "retain-on-failure",
    video: "retain-on-failure",
    screenshot: "only-on-failure",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  // Uncomment to let Playwright manage the Vite dev server lifecycle:
  // webServer: {
  //   command: "npm run dev:frontend",
  //   url: FRONTEND_URL,
  //   reuseExistingServer: !process.env.CI,
  //   timeout: 60_000,
  //   stdout: "pipe",
  //   stderr: "pipe",
  // },
})
`,

  "vite.e2e.config.ts": `/**
 * Vite config for the e2e test setup. Overlays the project's
 * canonical app vite.config with e2e-specific bits:
 *
 *   - envDir set to this directory so .env.e2e applies
 *   - viurTestingTokenFetch plugin: caches the test session token
 *   - withTokenInjection proxy entries: stamp X-Viur-Test-Token on
 *     every forwarded request, so the dev server is a transparent
 *     test-mode adapter
 *
 * TODO when running \`viur-testing-init\`:
 *   1. Adjust the relative path in \`import appConfig\` to point at
 *      your project's actual vite.config.
 *   2. Adjust the proxy paths / BACKEND constant if needed.
 */

import { defineConfig, mergeConfig, type UserConfig } from "vite"
import { dirname } from "node:path"
import { fileURLToPath } from "node:url"

import { viurTestingTokenFetch, withTokenInjection } from "@spltz/viur-testing"

// TODO: point this at your app's vite.config
import appConfig from "../../sources/app/vite.config"

const __dirname = dirname(fileURLToPath(import.meta.url))

const BACKEND = "http://localhost:8080"

const overrides: UserConfig = {
  envDir: __dirname,
  plugins: [viurTestingTokenFetch({ backendUrl: BACKEND })],
  server: {
    port: 8081,
    proxy: {
      "/vi/": withTokenInjection(BACKEND),
      "/json": withTokenInjection(BACKEND),
      "/static": { target: BACKEND, changeOrigin: false },
      "/resources": { target: BACKEND, changeOrigin: false },
    },
  },
}

export default mergeConfig(appConfig, defineConfig(overrides))
`,

  ".env.e2e": `# Vite env loaded when vite is started with \`--mode e2e --config vite.e2e.config.ts\`.
#
# VITE_API_URL pointed at the Vite dev server itself (NOT the backend)
# so the @viur/vue-utils Request wrapper prepends this to relative
# paths — every call lands on :8081 first, where the e2e Vite config's
# proxy forwards it to the backend with the X-Viur-Test-Token header
# attached. Single origin in the browser → no CORS preflight.
VITE_API_URL="http://localhost:8081"
`,

  ".gitignore": `node_modules/
test-results/
playwright-report/
playwright/.cache/
.auth/
*.log
`,

  "tests/example.spec.ts": `/**
 * example.spec.ts — minimal smoke test to verify the scaffolding works.
 *
 * Delete this file once you have a real test suite.
 */

import { test, expect } from "@spltz/viur-testing"

test("backend reports a valid test mode session", async ({ serverStatus }) => {
  expect(serverStatus.test_mode).toBe(true)
  expect(serverStatus.is_dev_server).toBe(true)
  expect(serverStatus.token).toMatch(/^[A-Za-z0-9_-]+$/)
})
`,
}

export interface InitOptions {
  /** Directory the CLI was invoked from. Default: `process.cwd()`. */
  cwd?: string
  /**
   * Override the resolved target directory. Used by the CLI wrapper
   * when the user passes a positional argument; relative paths are
   * resolved against `cwd`, absolute paths are used as-is. When
   * omitted, the target is `<cwd>/testing/e2e`.
   */
  target?: string
  /** Override the placeholder PROJECT name in templates. */
  projectName?: string
}

export function initProject(opts: InitOptions = {}): void {
  const cwd = opts.cwd ?? process.cwd()
  const targetDir = resolveTargetDir(cwd, opts.target)
  const projectName = opts.projectName ?? deriveProjectName(targetDir)

  console.log(`[viur-testing-init] scaffolding into ${targetDir}`)
  if (projectName !== "PROJECT") {
    console.log(`[viur-testing-init] project name: ${projectName}`)
  }

  let written = 0
  let skipped = 0

  for (const [relPath, rawContent] of Object.entries(TEMPLATES)) {
    const fullPath = join(targetDir, relPath)
    if (existsSync(fullPath)) {
      console.log(`  skip   ${relPath} (exists)`)
      skipped += 1
      continue
    }
    mkdirSync(dirname(fullPath), { recursive: true })
    const content = rawContent.replaceAll("PROJECT", projectName)
    writeFileSync(fullPath, content, "utf8")
    console.log(`  wrote  ${relPath}`)
    written += 1
  }

  console.log(
    `[viur-testing-init] done — ${written} file(s) written, ${skipped} skipped.`,
  )
  if (written > 0) {
    console.log()
    console.log("Next steps:")
    console.log("  1. Adjust the TODO markers in `vite.e2e.config.ts`.")
    console.log("  2. Run `npm install`.")
    console.log("  3. Boot your backend with `VIUR_TESTING_ENABLE=1 viur run`.")
    console.log("  4. `npm test`.")
  }
}

function resolveTargetDir(cwd: string, override: string | undefined): string {
  if (override === undefined) {
    return join(cwd, DEFAULT_RELATIVE_TARGET)
  }
  return isAbsolute(override) ? override : resolve(cwd, override)
}

function deriveProjectName(targetDir: string): string {
  // Walk up until we find a non-scoped package.json name, or hit /.
  // Intent: `cd testing/e2e && viur-testing-init` should produce a
  // sensible "<project>-e2e" name rather than literally "PROJECT".
  let dir = targetDir
  for (let depth = 0; depth < 8; depth += 1) {
    const pkgPath = join(dir, "..", "package.json")
    if (existsSync(pkgPath)) {
      try {
        const pkg = JSON.parse(readFileSync(pkgPath, "utf8")) as { name?: string }
        if (pkg.name && !pkg.name.startsWith("@") && pkg.name !== "root") {
          return pkg.name
        }
      } catch {
        // unreadable / malformed — keep walking
      }
    }
    const parent = dirname(dir)
    if (parent === dir) break
    dir = parent
  }
  return "PROJECT"
}
