#!/usr/bin/env node
// CLI entry — committed as plain .mjs so the shebang survives without
// post-build wrangling. The real logic lives in dist/bin/init.js (TS-built).

import { initProject } from "../dist/bin/init.js"

const args = process.argv.slice(2)

if (args.includes("-h") || args.includes("--help")) {
  console.log("Usage: viur-testing-init [--mode test|guarded] [--guarded] [target]")
  console.log("")
  console.log("Scaffolds a viur-testing-armed Playwright e2e suite.")
  console.log("")
  console.log("Without flags, prompts interactively for the scaffold mode")
  console.log("(when stdin is a TTY) — pick Test Mode or Guarded Mode. On a")
  console.log("non-TTY (CI, IDE task, …) defaults to Test Mode silently.")
  console.log("")
  console.log("Modes:")
  console.log("  test     Backend is a local dev server armed with")
  console.log("           VIUR_TESTING=test. Scaffolds Vite proxy +")
  console.log("           token-aware fixtures.")
  console.log("  guarded  Backend is an already-deployed instance. Scaffolds")
  console.log("           a slim setup; specs that need _test infrastructure")
  console.log("           auto-skip. PIN gate on every run.")
  console.log("")
  console.log("Flags:")
  console.log("  --mode test|guarded   Skip the interactive prompt.")
  console.log("  --guarded             Shortcut for --mode guarded.")
  console.log("  -h, --help            Show this message.")
  console.log("")
  console.log("Arguments:")
  console.log("  target   Directory to scaffold into. Relative paths are")
  console.log("           resolved against the current working directory.")
  console.log("           Defaults to `testing/e2e`.")
  console.log("")
  console.log("Examples:")
  console.log("  viur-testing-init")
  console.log("  viur-testing-init --guarded")
  console.log("  viur-testing-init --mode test testing/e2e")
  console.log("  viur-testing-init --guarded /tmp/scratch-suite")
  process.exit(0)
}

let mode  // undefined => prompt
const positional = []
for (let i = 0; i < args.length; i += 1) {
  const a = args[i]
  if (a === "--guarded") {
    mode = "guarded"
    continue
  }
  if (a === "--mode") {
    const value = args[i + 1]
    if (value !== "test" && value !== "guarded") {
      console.error(`viur-testing-init: --mode expects "test" or "guarded", got ${JSON.stringify(value)}.`)
      console.error("Run with --help for usage.")
      process.exit(1)
    }
    mode = value
    i += 1
    continue
  }
  if (a.startsWith("--mode=")) {
    const value = a.slice("--mode=".length)
    if (value !== "test" && value !== "guarded") {
      console.error(`viur-testing-init: --mode expects "test" or "guarded", got ${JSON.stringify(value)}.`)
      console.error("Run with --help for usage.")
      process.exit(1)
    }
    mode = value
    continue
  }
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
    mode,
  })
} catch (err) {
  console.error(`viur-testing-init: ${err.message ?? err}`)
  process.exit(1)
}
