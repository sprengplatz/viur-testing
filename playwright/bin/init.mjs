#!/usr/bin/env node
// CLI entry — committed as plain .mjs so the shebang survives without
// post-build wrangling. The real logic lives in dist/bin/init.js (TS-built).

import { initProject } from "../dist/bin/init.js"

const args = process.argv.slice(2)

if (args.includes("-h") || args.includes("--help")) {
  console.log("Usage: viur-testing-init [target]")
  console.log("")
  console.log("Scaffolds a viur-testing-armed Playwright e2e suite.")
  console.log("")
  console.log("Arguments:")
  console.log("  target   Directory to scaffold into. Relative paths are")
  console.log("           resolved against the current working directory.")
  console.log("           Defaults to `testing/e2e` (so running this from")
  console.log("           the repo root drops everything under testing/e2e/).")
  console.log("")
  console.log("Examples:")
  console.log("  viur-testing-init")
  console.log("  viur-testing-init testing/e2e")
  console.log("  viur-testing-init /tmp/scratch-suite")
  process.exit(0)
}

const positional = args.filter((a) => !a.startsWith("-"))
if (positional.length > 1) {
  console.error("viur-testing-init: at most one positional argument is supported.")
  console.error("Run with --help for usage.")
  process.exit(1)
}

initProject({
  cwd: process.cwd(),
  target: positional[0],
})
