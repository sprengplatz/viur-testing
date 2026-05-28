/**
 * Interactive 6-digit PIN challenge — the human-in-the-loop gate that
 * stands between `playwright test` and a guarded-mode run against a
 * live (= non-test-mode) backend.
 *
 * Design intent:
 *
 * - **Every run requires confirmation.** No persisted ACK file, no
 *   env-var bypass — those would silently inherit a months-old
 *   decision. The PIN is fresh per run and forces the developer to
 *   look at the screen.
 * - **One try, no retry.** A retry loop invites muscle-memory
 *   ("typo, again, again, …"). Wrong PIN aborts; re-running issues
 *   a new PIN.
 * - **No TTY → no run.** Without an interactive terminal there is
 *   no human to challenge, so guarded mode simply refuses. Same
 *   rule applies to CI by design — guarded mode is for developer
 *   hands only.
 * - **The backend URL is part of the prompt.** Wrong-URL-drift
 *   (developer ACK'd staging months ago, CI silently changed to
 *   production) cannot happen because the developer sees the URL
 *   right above the PIN every single time.
 */

import { createInterface, type Interface as ReadlineInterface } from "node:readline/promises"
import { stdin, stdout } from "node:process"

/**
 * Injectable I/O surface so the challenge can be exercised in tests
 * without a real TTY. The default implementation
 * (:data:`defaultPinChallengeIo`) wires up :data:`process.stdin` /
 * :data:`process.stdout` via the standard ``readline`` module.
 */
export interface PinChallengeIo {
  /** True if stdin is connected to an interactive terminal. */
  isTty(): boolean
  /** Print one line to the user — ANSI escapes are passed through. */
  writeLine(line: string): void
  /** Display a prompt and resolve with the user's reply (one line). */
  readLine(prompt: string): Promise<string>
}

/** Default I/O implementation: real ``process.stdin``/``stdout``. */
export const defaultPinChallengeIo: PinChallengeIo = {
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

// ANSI SGR for yellow bold — the digits stand out without making the
// whole banner look like an emergency. Reset (`\x1b[0m`) always
// follows so terminals that interpret one but not the other don't
// leave the rest of the line tinted.
const YELLOW = "\x1b[1;33m"
const RESET = "\x1b[0m"

/** Generate a fresh 6-digit numeric PIN. */
function generatePin(): string {
  let out = ""
  for (let i = 0; i < 6; i += 1) {
    out += Math.floor(Math.random() * 10).toString()
  }
  return out
}

/** Render the PIN with single spaces between digits, as agreed:
 * ``"841739"`` → ``"8 4 1 7 3 9"``. Easier to read aloud and easier
 * to type without losing one's place. */
function formatPinForDisplay(pin: string): string {
  return pin.split("").join(" ")
}

export interface RunPinChallengeOptions {
  /** Backend URL displayed above the PIN — drift signal for the user. */
  backendUrl: string
  /** I/O override (tests use this; production passes nothing). */
  io?: PinChallengeIo
  /** PIN override (tests use this; production generates fresh). */
  _pin?: string
}

/**
 * Run the PIN challenge. Resolves on success; throws on failure
 * (wrong PIN, missing TTY, empty input).
 *
 * Side effects: writes the banner + reads one line of input via
 * the supplied :data:`PinChallengeIo`.
 */
export async function runPinChallenge(opts: RunPinChallengeOptions): Promise<void> {
  const io = opts.io ?? defaultPinChallengeIo

  if (!io.isTty()) {
    throw new Error(
      "viur-testing guarded mode: stdin is not a TTY. " +
        "Run from an interactive terminal.",
    )
  }

  const pin = opts._pin ?? generatePin()

  io.writeLine("")
  io.writeLine("⚠  GUARDED MODE")
  io.writeLine(`   Target backend:  ${opts.backendUrl}`)
  io.writeLine("   The backend is NOT in test mode. Tests will interact with")
  io.writeLine("   the default Database — no test database, no token guard,")
  io.writeLine("   no _test/ fixture endpoints. Specs that use _test")
  io.writeLine("   infrastructure are auto-skipped.")
  io.writeLine("")
  io.writeLine(`   Confirm by typing:   ${YELLOW}${formatPinForDisplay(pin)}${RESET}`)
  io.writeLine("")

  const reply = (await io.readLine("   > ")).replace(/\s+/g, "")
  if (reply !== pin) {
    throw new Error(
      "viur-testing guarded mode: PIN confirmation failed. " +
        "Re-run the suite for a fresh PIN.",
    )
  }
}
