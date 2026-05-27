/**
 * Hard guard: refuse to start a test run if any spec file imports
 * directly from `@playwright/test` (instead of going through the
 * `@spltz/viur-testing` re-export of `test` + `expect`, which
 * injects the mandatory X-Viur-Test-Token header on every request).
 *
 * Without that header viur-testing's TokenValidator rejects every
 * non-bootstrap request with 403. ESLint can catch this at lint
 * time, but `npx playwright test` bypasses lint — call this from
 * `globalSetup` so the run aborts BEFORE Playwright spins up workers.
 */

import { readdirSync, readFileSync, statSync } from "node:fs"
import { extname, join, relative } from "node:path"

const FORBIDDEN_IMPORT_RE = /from\s+["']@playwright\/test["']/

function walk(dir: string): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir)) {
    const p = join(dir, entry)
    const st = statSync(p)
    if (st.isDirectory()) {
      out.push(...walk(p))
    } else if (st.isFile() && [".ts", ".tsx", ".mts"].includes(extname(p))) {
      out.push(p)
    }
  }
  return out
}

export function assertNoDirectPlaywrightImports(testsDir: string): void {
  const offenders: string[] = []
  for (const file of walk(testsDir)) {
    const content = readFileSync(file, "utf8")
    if (FORBIDDEN_IMPORT_RE.test(content)) {
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
      `(or via the project's re-export) so the X-Viur-Test-Token header is ` +
      `attached to every request. The bare @playwright/test fixtures bypass ` +
      `that wiring and every request from such a spec would be answered ` +
      `with 403 by the viur-testing TokenValidator.`,
  )
}
