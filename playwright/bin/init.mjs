#!/usr/bin/env node
// CLI entry — committed as plain .mjs so the shebang survives without
// post-build wrangling. The real logic lives in dist/bin/init.js (TS-built).

import { initProject } from "../dist/bin/init.js"

const args = process.argv.slice(2)

if (args.includes("-h") || args.includes("--help")) {
  console.log("Usage: viur-testing-init [target]")
  console.log("")
  console.log("Scaffolds a viur-testing-armed Playwright e2e suite (test mode).")
  console.log("")
  console.log("The backend is expected to be a local dev server armed with")
  console.log("VIUR_TESTING=test. Scaffolds a Vite proxy + token-aware fixtures.")
  console.log("")
  console.log("Flags:")
  console.log("  -h, --help   Show this message.")
  console.log("")
  console.log("Arguments:")
  console.log("  target   Directory to scaffold into. Relative paths are")
  console.log("           resolved against the current working directory.")
  console.log("           When omitted, the CLI walks up (max 10 levels)")
  console.log("           looking for a `deploy/` directory, suggests")
  console.log("           `<root>/testing/e2e`, and asks you to confirm or")
  console.log("           adjust the path.")
  console.log("")
  console.log("Examples:")
  console.log("  viur-testing-init")
  console.log("  viur-testing-init testing/e2e")
  console.log("  viur-testing-init /tmp/scratch-suite")
  process.exit(0)
}

const positional = []
for (let i = 0; i < args.length; i += 1) {
  const a = args[i]
  if (a.startsWith("-")) {
    console.error(`viur-testing-init: unknown flag ${JSON.stringify(a)}.`)
    console.error("Run with --help for usage.")
    process.exit(1)
  }
  positional.push(a)
}

if (positional.length > 1) {
  console.error("viur-testing-init: at most one positional argument is supported.")
  console.error("Run with --help for usage.")
  process.exit(1)
}

try {
  await initProject({
    cwd: process.cwd(),
    target: positional[0],
  })
} catch (err) {
  console.error(`viur-testing-init: ${err.message ?? err}`)
  process.exit(1)
}
