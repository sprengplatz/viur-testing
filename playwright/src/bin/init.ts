/**
 * Scaffolding logic for `viur-testing-init`.
 *
 * Drops the standard set of e2e-suite files into a target directory.
 * Re-runnable — already-existing files are skipped, never overwritten.
 *
 * Scaffolds a single **test-mode** suite: the backend is a local dev
 * server armed with ``VIUR_TESTING=test``. The generated files include
 * a Vite-proxy config that turns the dev server into a transparent
 * test-mode adapter, plus an example spec that consumes the
 * ``serverStatus`` fixture.
 *
 * The entry point lives in `bin/init.mjs` (a tiny shebang wrapper)
 * so npm can resolve the bin without TS-compiler shebang quirks.
 */

import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs"
import { dirname, isAbsolute, join, resolve } from "node:path"
import { createInterface, type Interface as ReadlineInterface } from "node:readline/promises"
import { stdin, stdout } from "node:process"
import { fileURLToPath } from "node:url"

/** Subdirectory (relative to the detected project root) where the e2e suite lands. */
const DEFAULT_RELATIVE_TARGET = "testing/e2e"

/** Directory name we walk up the tree looking for to anchor the project root. */
const PROJECT_ROOT_MARKER = "deploy"

/** How many directory levels above `cwd` we probe for the marker. */
const MAX_ROOT_LOOKUP_LAYERS = 10

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
 * in TEST MODE (backend armed with VIUR_TESTING=test).
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

/**
 * Backend-side scaffolding. Lives as a sibling of the e2e suite
 * (``testing/api`` next to ``testing/e2e``), so the keys are written
 * relative to the e2e target with a leading ``../``.
 *
 * ``api/__init__.py`` is the project's test-API package: Python modules
 * dropped here are picked up by viur-testing and exposed under
 * ``/json/_test/...`` when the server runs in test mode — that is the
 * backend half of the per-spec fixtures the e2e suite calls.
 */
const API_TEMPLATES: Record<string, string> = {
  "../api/__init__.py": `"""Project-specific test API extensions.

Python modules placed here are picked up by viur-testing and exposed under
\`/json/_test/...\` when the server runs in test mode (\`VIUR_TESTING=test\`).

Use this to:
- seed test data (users, dealers, articles, carts) from a known state
- expose project-specific test fixtures the e2e suite calls before/after tests
- tear down or reset state between scenarios

Modules added here should follow ViUR's Module conventions (subclass
\`viur.core.Module\`, expose actions via \`@exposed\`).
"""
`,

  "../api/user.py": `import logging

from viur.core import Module, conf, db, skeleton, utils
from viur.core.decorators import exposed, force_post
from viur.core.modules.user import Status

# Written into the firstname bone of every user created by this spec so
# teardown can find and remove exactly the accounts it owns — never a
# real user. Keep it improbable as a real first name.
TEST_USER_MARKER = "viur-e2e-test"


class UserTestApi(Module):
    """Spec module: setup/teardown test users

    Mounted at /_test/user/.

    Endpoints:
      setup          — create test user
      teardown       — deletes all created users
    """

    json = True
    accessRights = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @exposed
    @force_post
    def setup(self) -> dict:
        """Create a fresh, active test user and return its login credentials.

        The e2e suite calls this in \`\`beforeAll\`\` and logs in with the
        returned \`\`credentials\`\`. The account is tagged via
        :data:\`TEST_USER_MARKER\` so :meth:\`teardown\` can clean it up.
        """
        user_module = conf.main_app.vi.user
        # skeletonByKind ensures we get the full skeleton (incl. the
        # password bone added by UserPassword), matching how viur-core
        # creates the initial admin user.
        skel = skeleton.skeletonByKind(user_module.addSkel().kindName)()

        name = f"e2e+{utils.string.random(12)}@test.local"
        password = utils.string.random(16)

        skel["name"] = name
        skel["firstname"] = TEST_USER_MARKER
        skel["lastname"] = "E2E"
        skel["password"] = password
        skel["status"] = Status.ACTIVE  # enabled right away, no email/admin gate
        skel["access"] = ["root"]

        skel.write()

        logging.info("[viur-e2e] created test user %r", name)
        return {"credentials": {"name": name, "password": password}}

    @exposed
    @force_post
    def teardown(self) -> dict:
        """Delete every user this spec created, identified by the marker.

        Uses \`\`skel.delete()\`\` (not a raw datastore delete) so the unique
        lock on the e-mail bone is released — otherwise the address would
        stay reserved and re-runs could collide.
        """
        kind = conf.main_app.vi.user.addSkel().kindName
        deleted = 0

        for entity in db.Query(kind).filter("firstname.idx =", TEST_USER_MARKER).iter():
            skel = skeleton.skeletonByKind(kind)()
            try:
                skel.delete(entity.key)
                deleted += 1
            except Exception as exc:  # keep going — one bad row must not block cleanup
                logging.exception("[viur-e2e] failed to delete test user %s: %s", entity.key, exc)

        logging.info("[viur-e2e] teardown removed %d test user(s)", deleted)
        return {"deleted": deleted}
`,
}

function buildTemplates(): Record<string, string> {
  return { ...COMMON_TEMPLATES, ...TEST_MODE_TEMPLATES, ...API_TEMPLATES }
}

// ---------------------------------------------------------------------------
// Project-root detection + interactive target confirmation
// ---------------------------------------------------------------------------

/**
 * Injectable I/O surface for the target-directory confirmation prompt
 * so the interactive path is testable without a real TTY. Production
 * code uses :data:`defaultInitPromptIo`.
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

/**
 * Walk up from ``startDir`` (inclusive) looking for a directory that
 * contains a ``deploy/`` child. That directory is treated as the
 * project root — the e2e suite is anchored there rather than wherever
 * the CLI happened to be invoked. Returns ``null`` if no marker is
 * found within :data:`MAX_ROOT_LOOKUP_LAYERS` levels.
 */
function findProjectRoot(startDir: string): string | null {
  let dir = startDir
  for (let depth = 0; depth <= MAX_ROOT_LOOKUP_LAYERS; depth += 1) {
    const candidate = join(dir, PROJECT_ROOT_MARKER)
    try {
      if (existsSync(candidate) && statSync(candidate).isDirectory()) {
        return dir
      }
    } catch {
      // unreadable entry — keep walking
    }
    const parent = dirname(dir)
    if (parent === dir) break
    dir = parent
  }
  return null
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
   * omitted, the target is derived from the detected project root
   * (the closest ancestor containing a ``deploy/`` directory) and the
   * user is asked to confirm or adjust it.
   */
  target?: string
  /** Override the placeholder PROJECT name in templates. */
  projectName?: string
  /** Prompt I/O override — used in tests. */
  _io?: InitPromptIo
}

export async function initProject(opts: InitOptions = {}): Promise<void> {
  const cwd = opts.cwd ?? process.cwd()
  const io = opts._io ?? defaultInitPromptIo
  const targetDir = await resolveTargetDir(cwd, opts.target, io)
  const projectName = opts.projectName ?? deriveProjectName(targetDir)
  const viurTestingVersionRange = detectOwnVersionRange()
  const templates = buildTemplates()

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
    console.log("  1. Adjust the TODO markers in `vite.e2e.config.ts`.")
    console.log("  2. Run `npm install`.")
    console.log("  3. Boot your backend with `VIUR_TESTING=test viur run`.")
    console.log("  4. `npm test`.")
  }
}

async function resolveTargetDir(
  cwd: string,
  override: string | undefined,
  io: InitPromptIo,
): Promise<string> {
  // Explicit positional argument always wins — no detection, no prompt.
  if (override !== undefined) {
    return isAbsolute(override) ? override : resolve(cwd, override)
  }

  const root = findProjectRoot(cwd)
  const suggested = root
    ? join(root, DEFAULT_RELATIVE_TARGET)
    : join(cwd, DEFAULT_RELATIVE_TARGET)

  // Non-interactive (CI, IDE task, piped stdin): take the suggestion
  // and log how it was derived — there is no human to confirm.
  if (!io.isTty()) {
    if (root) {
      console.log(`[viur-testing-init] found "${PROJECT_ROOT_MARKER}/" project root: ${root}`)
    } else {
      console.log(
        `[viur-testing-init] no "${PROJECT_ROOT_MARKER}/" directory found within ` +
          `${MAX_ROOT_LOOKUP_LAYERS} levels above ${cwd} — using current directory.`,
      )
    }
    return suggested
  }

  io.writeLine("")
  if (root) {
    io.writeLine(`Found "${PROJECT_ROOT_MARKER}/" project root: ${root}`)
  } else {
    io.writeLine(
      `No "${PROJECT_ROOT_MARKER}/" directory found within ${MAX_ROOT_LOOKUP_LAYERS} ` +
        `levels above the current directory.`,
    )
  }
  io.writeLine(`Suggested e2e suite location: ${suggested}`)
  io.writeLine("")

  const reply = (
    await io.readLine("Press Enter to accept, or type a different path: ")
  ).trim()
  if (reply === "") return suggested
  return isAbsolute(reply) ? reply : resolve(cwd, reply)
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
