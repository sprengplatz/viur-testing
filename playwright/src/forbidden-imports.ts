/**
 * Hard guard: refuse to start a test run if any spec file imports
 * directly from `@playwright/test` (instead of going through the
 * `@spltz/viur-testing` re-export of `test` + `expect`, which
 * sets the mandatory viur-test-token cookie on every request).
 *
 * Without that cookie viur-testing's TokenValidator rejects every
 * non-bootstrap request with 403. ESLint can catch this at lint
 * time, but `npx playwright test` bypasses lint — call this from
 * `globalSetup` so the run aborts BEFORE Playwright spins up workers.
 */

import { existsSync, readdirSync, readFileSync, statSync } from "node:fs"
import { extname, join, relative } from "node:path"

const FORBIDDEN_IMPORT_RE = /from\s+["']@playwright\/test["']/

/**
 * Strip line + block comments from *source*.
 *
 * Pragmatic, not a full TypeScript parser. The goal is to keep
 * comments mentioning the forbidden phrase from being mistaken for
 * actual imports — the most common false-positive source in real
 * codebases (JSDoc with example imports, inline "do not do this"
 * warnings):
 *
 * - ``// don't: from "@playwright/test"``        — line comment, dropped.
 * - ``/* example: from "@playwright/test" *\/`` — block comment, dropped.
 *
 * String literals are NOT stripped: doing so would also wipe the
 * ``"@playwright/test"`` module specifier of a real import statement,
 * defeating the whole point of the scan. The remaining edge case is a
 * spec file embedding the literal phrase inside a string (e.g.
 * ``expect(...).toThrow("import from '@playwright/test'")``) — very
 * rare in practice; if you do hit it, refactor the assertion to use a
 * partial match.
 */
function stripComments(source: string): string {
  let out = source
  // Block comments first — ``//`` inside a block must not be treated
  // as a line comment.
  out = out.replace(/\/\*[\s\S]*?\*\//g, "")
  out = out.replace(/\/\/[^\n]*/g, "")
  return out
}

/**
 * Directories the walker must never descend into.
 *
 * `node_modules` is the catastrophic one: without it, scanning a
 * `testsDir` that contains its own dependency tree (a nested install,
 * a monorepo symlink) would flag thousands of unrelated files because
 * Playwright's own fixture set unsurprisingly contains
 * `from "@playwright/test"` imports.
 *
 * `.git`, `dist`, `build`, `coverage`, `playwright-report`,
 * `test-results` and `.next` are added defensively — they may contain
 * compiled JS/TS, snapshots, vendored copies or generated artefacts
 * that would trigger false positives and slow the walk dramatically.
 */
const SKIPPED_DIRS = new Set([
  "node_modules",
  ".git",
  ".next",
  "build",
  "coverage",
  "dist",
  "playwright-report",
  "test-results",
])

const SCANNED_EXTENSIONS = [".ts", ".tsx", ".mts"]

function walk(dir: string): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir)) {
    if (SKIPPED_DIRS.has(entry)) continue
    const p = join(dir, entry)
    const st = statSync(p)
    if (st.isDirectory()) {
      out.push(...walk(p))
    } else if (st.isFile() && SCANNED_EXTENSIONS.includes(extname(p))) {
      out.push(p)
    }
  }
  return out
}

export function assertNoDirectPlaywrightImports(testsDir: string): void {
  if (!existsSync(testsDir)) {
    // A missing testsDir is almost always a misconfiguration of
    // ``createGlobalSetup({ testsDir })`` rather than an empty suite.
    // Reading dir would throw an opaque ENOENT — print something the
    // user can act on instead.
    throw new Error(
      `viur-testing: assertNoDirectPlaywrightImports got testsDir=` +
        `${JSON.stringify(testsDir)}, which does not exist. ` +
        `Pass an explicit testsDir to createGlobalSetup({...}) or run ` +
        `playwright from the directory that contains your tests/ folder.`,
    )
  }

  const offenders: string[] = []
  for (const file of walk(testsDir)) {
    const content = readFileSync(file, "utf8")
    if (FORBIDDEN_IMPORT_RE.test(stripComments(content))) {
      offenders.push(relative(process.cwd(), file))
    }
  }
  if (offenders.length === 0) {
    return
  }
  const list = offenders.map((f) => `  - ${f}`).join("\n")
  throw new Error(
    `viur-testing: refusing to start the suite — ${offenders.length} spec ` +
      `file(s) import directly from "@playwright/test":\n${list}\n\n` +
      `Spec files must import { test, expect } from "@spltz/viur-testing" ` +
      `(or via the project's re-export) so the viur-test-token cookie is ` +
      `attached to every request. The bare @playwright/test fixtures bypass ` +
      `that wiring and every request from such a spec would be answered ` +
      `with 403 by the viur-testing TokenValidator.`,
  )
}
