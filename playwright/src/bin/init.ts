/**
 * Scaffolding logic for `viur-testing-init`.
 *
 * Drops the standard set of e2e-suite files into a target directory.
 * Re-runnable — already-existing files are skipped, never overwritten.
 *
 * Two scaffold modes:
 *
 *   - **test** (default): backend is a local dev server with
 *     ``VIUR_TESTING_ENABLE=1``. Scaffolds a Vite-proxy config so
 *     the dev server is a transparent test-mode adapter, plus an
 *     example spec that consumes the ``serverStatus`` fixture.
 *
 *   - **guarded**: backend is an already-deployed instance with no
 *     ``/_test/`` endpoints. Scaffolds a slim setup that drives the
 *     live application via Playwright directly — no Vite, no
 *     ``.env.e2e``, no token-aware fixtures. The example spec is a
 *     public-page smoke test.
 *
 * Mode selection happens interactively when stdin is a TTY (the
 * common case for ``npx viur-testing-init``). The CLI also accepts
 * ``--mode test|guarded`` (and the ``--guarded`` shortcut) to skip
 * the prompt — useful when scaffolding from a script or CI.
 *
 * The entry point lives in `bin/init.mjs` (a tiny shebang wrapper)
 * so npm can resolve the bin without TS-compiler shebang quirks.
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs"
import { dirname, isAbsolute, join, resolve } from "node:path"
import { createInterface, type Interface as ReadlineInterface } from "node:readline/promises"
import { stdin, stdout } from "node:process"
import { fileURLToPath } from "node:url"

/** Default subdirectory beneath `cwd` where the e2e suite gets scaffolded. */
const DEFAULT_RELATIVE_TARGET = "testing/e2e"

export type ScaffoldMode = "test" | "guarded"

/**
 * SemVer caret range for the published ``@spltz/viur-testing`` package,
 * read from this package's own ``package.json`` at runtime. Injected
 * into the generated host ``package.json`` in place of the
 * ``VIUR_TESTING_VERSION_RANGE`` placeholder.
 *
 * Why not hard-coded? A static string would silently rot whenever the
 * package is bumped — scaffolded projects would carry a stale floor.
 * Why ``^``? Caret pins to compatible-with-this-major; once the
 * package goes 1.0 the host gets minor/patch updates automatically
 * but never a breaking major. Pre-1.0, ``^`` is conservative (locks
 * to the same ``0.x`` minor); that is intentional because we are
 * still iterating on the wire format.
 */
function detectOwnVersionRange(): string {
  // dist/bin/init.js → ../../package.json. In source (.ts) we are at
  // src/bin/init.ts → ../../package.json. ``fileURLToPath`` works in
  // both compiled and ts-node-style executions.
  const here = dirname(fileURLToPath(import.meta.url))
  const pkgPath = join(here, "..", "..", "package.json")
  try {
    const pkg = JSON.parse(readFileSync(pkgPath, "utf8")) as { version?: string }
    if (pkg.version && /^\d+\.\d+\.\d+/.test(pkg.version)) {
      return `^${pkg.version}`
    }
  } catch {
    // Unreadable / corrupted manifest — fall through to the safe default.
  }
  // Defensive fallback: pin to the current published floor so the
  // scaffold is never left with a wildcard.
  return "^0.1.0"
}

// ---------------------------------------------------------------------------
// Templates
// ---------------------------------------------------------------------------

const COMMON_TEMPLATES: Record<string, string> = {
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

  ".gitignore": `node_modules/
test-results/
playwright-report/
playwright/.cache/
.auth/
*.log
`,
}

const TEST_MODE_TEMPLATES: Record<string, string> = {
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
    "install-browsers": "playwright install --with-deps chromium"
  },
  "//dev:frontend": "If your project has a Vite frontend, add a script that boots it on :8081 using vite.e2e.config.ts — see the TODO in vite.e2e.config.ts.",
  "devDependencies": {
    "@playwright/test": "^1.49.0",
    "@spltz/viur-testing": "VIUR_TESTING_VERSION_RANGE",
    "@types/node": "^22.10.0",
    "typescript": "^5.6.0"
  }
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
 * Vite config for the e2e test setup. Stands alone — works out of the
 * box for a backend-only proxy. If your project also has a Vite
 * frontend whose own vite.config you want to layer on top, follow the
 * "OVERLAY" TODO at the bottom of this file.
 *
 * What this config does:
 *
 *   - envDir set to this directory so .env.e2e applies
 *   - viurTestingTokenFetch plugin: caches the test session token at
 *     server start, refreshes on observed 403s and on TTL expiry
 *   - withTokenInjection proxy entries: stamp X-Viur-Test-Token on
 *     every forwarded request, so the dev server is a transparent
 *     test-mode adapter for the backend
 */

import { defineConfig, type UserConfig } from "vite"
import { dirname } from "node:path"
import { fileURLToPath } from "node:url"

import { viurTestingTokenFetch, withTokenInjection } from "@spltz/viur-testing"

const __dirname = dirname(fileURLToPath(import.meta.url))

// TODO: adjust if your backend listens on a different port.
const BACKEND = "http://localhost:8080"

const e2eConfig: UserConfig = {
  envDir: __dirname,
  plugins: [viurTestingTokenFetch({ backendUrl: BACKEND })],
  server: {
    port: 8081,
    proxy: {
      // TODO: keep the routes that match your backend's actual mount
      // points. Anything you remove will not get the test-token
      // header injected and will 403 from viur-testing's
      // TokenValidator.
      "/vi/": withTokenInjection(BACKEND),
      "/json": withTokenInjection(BACKEND),
      "/static": { target: BACKEND, changeOrigin: false },
      "/resources": { target: BACKEND, changeOrigin: false },
    },
  },
}

// OVERLAY (optional): if your frontend has its own vite.config that
// you want to layer the e2e overrides on top of, uncomment the two
// lines below and replace the export with the mergeConfig form:
//
//   import { mergeConfig } from "vite"
//   import appConfig from "../path/to/your/app/vite.config"
//   export default mergeConfig(appConfig, defineConfig(e2eConfig))
//
// Add a "dev:frontend" script in package.json that boots the
// frontend with this overlay, e.g.:
//
//   "dev:frontend": "vite --config vite.e2e.config.ts --port 8081"

export default defineConfig(e2eConfig)
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

  "tests/example.spec.ts": `/**
 * example.spec.ts — minimal smoke test to verify the scaffolding works
 * in TEST MODE (backend armed with VIUR_TESTING_ENABLE=1).
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

const GUARDED_MODE_TEMPLATES: Record<string, string> = {
  "package.json": `{
  "name": "PROJECT-e2e",
  "private": true,
  "version": "0.1.0",
  "description": "End-to-end Playwright smoke tests for PROJECT (guarded mode).",
  "type": "module",
  "scripts": {
    "test": "playwright test",
    "test:headed": "playwright test --headed",
    "test:ui": "playwright test --ui",
    "report": "playwright show-report",
    "install-browsers": "playwright install --with-deps chromium"
  },
  "devDependencies": {
    "@playwright/test": "^1.49.0",
    "@spltz/viur-testing": "VIUR_TESTING_VERSION_RANGE",
    "@types/node": "^22.10.0",
    "typescript": "^5.6.0"
  }
}
`,

  "playwright.config.ts": `import { defineConfig, devices } from "@playwright/test"

// Guarded Mode: tests run against an already-deployed instance.
// Set E2E_BACKEND_URL to point at the target, e.g.:
//   E2E_BACKEND_URL=https://staging.example.com npm test
//
// On every run the runner probes /json/_test/config/status — if it
// returns 404 (no test mode), an interactive 6-digit PIN gate
// appears in the terminal. Wrong PIN aborts; the suite never
// starts. See https://sprengplatz.github.io/viur-testing/guarded-mode/
// for details.
const BACKEND_URL = process.env.E2E_BACKEND_URL ?? "https://example.com"

// globalSetup picks this up via process.env — set here so a single
// override on the playwright CLI flows everywhere consistently.
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
    baseURL: BACKEND_URL,
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
})
`,

  "tests/example.spec.ts": `/**
 * example.spec.ts — public-page smoke test for GUARDED MODE.
 *
 * Replace the body with assertions that match your actual deployed
 * page. Delete this file once you have a real test suite.
 *
 * See https://sprengplatz.github.io/viur-testing/guarded-mode/ for
 * details on which fixtures auto-skip and why.
 */

import { test, expect } from "@spltz/viur-testing"

test("homepage renders", async ({ page }) => {
  await page.goto("/")
  // Trivial check: any non-empty <title>. Tighten this once you
  // know what the page actually looks like.
  await expect(page).toHaveTitle(/.+/)
})
`,
}

function buildTemplates(mode: ScaffoldMode): Record<string, string> {
  const modeSpecific = mode === "guarded" ? GUARDED_MODE_TEMPLATES : TEST_MODE_TEMPLATES
  return { ...COMMON_TEMPLATES, ...modeSpecific }
}

// ---------------------------------------------------------------------------
// Interactive prompt
// ---------------------------------------------------------------------------

/**
 * Injectable I/O surface for the scaffold-mode prompt so the
 * interactive path is testable without a real TTY. Production code
 * uses :data:`defaultInitPromptIo`.
 */
export interface InitPromptIo {
  isTty(): boolean
  writeLine(line: string): void
  readLine(prompt: string): Promise<string>
}

export const defaultInitPromptIo: InitPromptIo = {
  isTty(): boolean {
    return Boolean(stdin.isTTY)
  },
  writeLine(line: string): void {
    stdout.write(line + "\n")
  },
  async readLine(prompt: string): Promise<string> {
    const rl: ReadlineInterface = createInterface({ input: stdin, output: stdout })
    try {
      return await rl.question(prompt)
    } finally {
      rl.close()
    }
  },
}

async function promptForMode(io: InitPromptIo): Promise<ScaffoldMode> {
  io.writeLine("")
  io.writeLine("Which scaffold do you want?")
  io.writeLine("")
  io.writeLine("  [1] Test Mode  (default)")
  io.writeLine("      Backend is a local dev server with VIUR_TESTING_ENABLE=1.")
  io.writeLine("      Scaffolds Vite proxy + token-aware fixtures.")
  io.writeLine("")
  io.writeLine("  [2] Guarded Mode")
  io.writeLine("      Backend is an already-deployed instance (no test database,")
  io.writeLine("      no _test/ endpoints). Scaffolds a slim setup; specs that")
  io.writeLine("      need _test infrastructure auto-skip.")
  io.writeLine("")

  const reply = (await io.readLine("  Select [1/2, default 1]: ")).trim().toLowerCase()
  if (reply === "" || reply === "1" || reply === "test") return "test"
  if (reply === "2" || reply === "guarded" || reply === "g") return "guarded"
  // Anything else → bail with a clear message rather than silently
  // defaulting; an unexpected input usually means the user meant
  // something specific.
  throw new Error(
    `viur-testing-init: unrecognised selection ${JSON.stringify(reply)}. ` +
      `Expected 1/2 (or "test"/"guarded"). Re-run and pick a valid option, ` +
      `or pass --mode <test|guarded> to skip the prompt.`,
  )
}

/**
 * Resolve the scaffold mode. Explicit ``opts.mode`` wins; otherwise
 * we prompt when stdin is a TTY, or default to ``test`` (with a log
 * line) when it is not — that preserves the pre-0.3 behaviour of
 * ``viur-testing-init`` in non-interactive contexts (CI scaffolding,
 * IDE tasks without TTY).
 */
async function resolveMode(
  explicit: ScaffoldMode | undefined,
  io: InitPromptIo,
): Promise<ScaffoldMode> {
  if (explicit !== undefined) return explicit
  if (!io.isTty()) {
    console.log(
      `[viur-testing-init] no TTY — defaulting to "test" mode. ` +
        `Pass --mode test|guarded (or --guarded) to override.`,
    )
    return "test"
  }
  return await promptForMode(io)
}

// ---------------------------------------------------------------------------
// initProject
// ---------------------------------------------------------------------------

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
  /**
   * Scaffold mode. When omitted, prompts on TTY and defaults to
   * ``"test"`` on non-TTY. Pass explicitly to skip the prompt.
   */
  mode?: ScaffoldMode
  /** Prompt I/O override — used in tests. */
  _io?: InitPromptIo
}

export async function initProject(opts: InitOptions = {}): Promise<void> {
  const cwd = opts.cwd ?? process.cwd()
  const targetDir = resolveTargetDir(cwd, opts.target)
  const projectName = opts.projectName ?? deriveProjectName(targetDir)
  const viurTestingVersionRange = detectOwnVersionRange()
  const io = opts._io ?? defaultInitPromptIo
  const mode = await resolveMode(opts.mode, io)
  const templates = buildTemplates(mode)

  console.log(`[viur-testing-init] mode: ${mode}`)
  console.log(`[viur-testing-init] scaffolding into ${targetDir}`)
  if (projectName !== "PROJECT") {
    console.log(`[viur-testing-init] project name: ${projectName}`)
  }
  console.log(`[viur-testing-init] @spltz/viur-testing pinned to ${viurTestingVersionRange}`)

  let written = 0
  let skipped = 0

  for (const [relPath, rawContent] of Object.entries(templates)) {
    const fullPath = join(targetDir, relPath)
    if (existsSync(fullPath)) {
      console.log(`  skip   ${relPath} (exists)`)
      skipped += 1
      continue
    }
    mkdirSync(dirname(fullPath), { recursive: true })
    const content = rawContent
      .replaceAll("PROJECT", projectName)
      .replaceAll("VIUR_TESTING_VERSION_RANGE", viurTestingVersionRange)
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
    if (mode === "test") {
      console.log("  1. Adjust the TODO markers in `vite.e2e.config.ts`.")
      console.log("  2. Run `npm install`.")
      console.log("  3. Boot your backend with `VIUR_TESTING_ENABLE=1 viur run`.")
      console.log("  4. `npm test`.")
    } else {
      console.log("  1. Set E2E_BACKEND_URL to your deployed backend's origin.")
      console.log("  2. Run `npm install`.")
      console.log("  3. `npm test` — confirm the 6-digit PIN gate on the terminal.")
    }
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
