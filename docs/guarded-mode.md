# Guarded Mode

*Available since `@spltz/viur-testing` 0.3.0 — Playwright runner side
only. The Python package is unaffected.*

## What it is

Guarded Mode lets Playwright drive smoke tests against an
**already-deployed application** — a public landing page, a
marketing site, an instance you do not control and cannot put into
test mode. There is no test database, no `X-Viur-Test-Token`
header, no `/_test/` endpoints. The browser behaves exactly as a
real user's browser would.

Because the safety net of the bilateral guarantee is not in force,
Guarded Mode is gated by a **fresh 6-digit PIN on every run**. No
persisted acknowledgement file, no env-var bypass — the developer
has to read the PIN off the terminal and type it back every single
time.

## When the runner enters it

`createGlobalSetup()` probes
`POST /json/_test/config/status` on the configured backend before
the suite starts. Three outcomes are possible:

| Probe outcome | Mode | What happens next |
|---|---|---|
| **HTTP 200** + validated test-mode payload | **Test Mode** | The existing flow: token issued, `.auth/token.json` written, fixtures inject `X-Viur-Test-Token` on every request. |
| **HTTP 404** | **Guarded Mode** | Interactive PIN challenge. On confirmation, suite runs against the live backend without any token injection. |
| 5xx, timeout, malformed JSON, integrity check failure | **Hard error** | Suite refuses to start. Ambiguous server state is **never** silently downgraded to Guarded Mode. |

The auto-detect happens transparently — there is no
`mode: "guarded"` flag in `playwright.config.ts`. Point the runner
at a target URL and the runner decides.

## The PIN challenge

```
$ npx playwright test

[viur-testing] probing https://staging.example.com/json/_test/config/status ...

⚠  GUARDED MODE
   Target backend:  https://staging.example.com
   The backend is NOT in test mode. Tests will interact with
   the live application — no test database, no token guard,
   no _test/ fixture endpoints. Specs that use _test
   infrastructure are auto-skipped.

   Confirm by typing:   8 4 1 7 3 9

   > _
```

Display rules:

- **6 random digits**, fresh per run.
- **Yellow + space-separated** (`8 4 1 7 3 9`) so you can read them
  off easily.
- **The target URL is printed above** the PIN — wrong-URL drift
  (e.g. CI silently flipped from staging to prod) is visible at a
  glance before you type.

Input rules:

- Whitespace between digits is ignored (`8 4 1 7 3 9` and
  `841739` both work).
- **Wrong PIN aborts the suite.** No retry loop. Re-running the
  suite issues a fresh PIN.
- **No TTY = no run.** If stdin is not connected to an interactive
  terminal (CI, background job, IDE task without an attached
  terminal), Guarded Mode raises *"viur-testing guarded mode: stdin
  is not a TTY. Run from an interactive terminal."* immediately.

## What changes inside the suite

A spec written for Test Mode does not need to be rewritten for
Guarded Mode. The fixtures and helpers adapt automatically:

- **`context` fixture** — in Test Mode it is born with
  `extraHTTPHeaders: { 'X-Viur-Test-Token': ... }`; in Guarded
  Mode it is a vanilla Playwright browser context with no
  injected headers.
- **`serverStatus` fixture** — auto-skips the consuming test in
  Guarded Mode (the backend has no test-mode payload to return).
- **`backendApi` fixture** — same: auto-skips. The token-carrying
  `APIRequestContext` cannot exist in Guarded Mode.
- **`callTestModule` / `callTestModuleRaw`** — auto-skip the
  consuming test or hook. Called from a `test.beforeAll` they
  skip all tests in the describe; called from a test body they
  skip that test only.

The skip is reported by Playwright as **skipped, not failed**, with
the reason *"uses _test infrastructure, skipped in guarded mode"*.
A run report looks like this:

```
Running 12 tests using 1 worker

  ✓ tests/public-landing.spec.ts:8:3   › renders hero (340ms)
  ✓ tests/public-landing.spec.ts:14:3  › nav links work (220ms)
  -  tests/user-login.spec.ts:5:3      › uses _test infrastructure …
  -  tests/user-login.spec.ts:18:3     › uses _test infrastructure …
  ✓ tests/footer.spec.ts:6:3            › privacy link present (180ms)
  ...
```

## What it does NOT do

- **No server-side cooperation.** The server is not in test mode
  and does not know it is being talked to by a test framework. No
  custom User-Agent, no marker header, no opt-in deny-list of
  destructive endpoints. The runner is honest about being a
  regular browser.
- **No persisted ACK.** No `.viur-testing/`-state, no env-var
  bypass. Every run is its own decision.
- **No CI support.** Guarded Mode requires a TTY. CI either
  points at a test-mode-armed backend (and falls into Test Mode
  automatically) or it does not use this package's globalSetup
  for that target at all.

## Wiring it up

The scaffolder ships a Guarded-Mode preset. From your project root:

```sh
npx viur-testing-init
```

…then pick `2` at the prompt (or run
`npx viur-testing-init --guarded` to skip the prompt). The
generated `testing/e2e/` is a slim setup: no `vite.e2e.config.ts`,
no `.env.e2e`, no token-aware fixtures in the example spec — just
a `playwright.config.ts` with `baseURL` pointing at
`E2E_BACKEND_URL` and an example test that opens the homepage.

If you scaffold by hand, the standard wiring works unchanged:

```ts
// playwright.config.ts
import { defineConfig } from "@playwright/test"
import { createGlobalSetup, createGlobalTeardown } from "@spltz/viur-testing"

export default defineConfig({
  globalSetup: createGlobalSetup(),
  globalTeardown: createGlobalTeardown(),
  // …
})
```

Point `E2E_BACKEND_URL` (or `createGlobalSetup({ backendUrl })`)
at a test-mode-armed backend → Test Mode runs. Point it at a
deployed instance → Guarded Mode runs with a PIN prompt. Mixed
runs in one process are impossible by construction — one
`globalSetup` call resolves to exactly one mode, propagated to
all workers via the `VIUR_TESTING_MODE` environment variable.

## Detecting the mode at runtime

If you need to branch inside a spec or fixture (rare — most specs
should not need to), inspect `process.env.VIUR_TESTING_MODE`:

```ts
import { MODE_ENV_VAR } from "@spltz/viur-testing"

if (process.env[MODE_ENV_VAR] === "guarded") {
  // running against a live backend, no _test infrastructure
}
```

Prefer the fixture auto-skip behaviour over manual branching — it
keeps the spec readable and the mode decision in one place.

## Public API for custom setups

If you need a non-standard setup flow (e.g. you write your own
globalSetup), the building blocks are exported:

- `probeStatusEndpoint(opts)` — just the probe, returns
  `{ kind: "armed", status }` or `{ kind: "unarmed" }`, throws
  on ambiguous responses.
- `detectMode(opts)` — probe + dispatch, runs the PIN challenge
  on `unarmed`. Returns `{ mode: "test", status }` or
  `{ mode: "guarded" }`.
- `runPinChallenge(opts)` — the interactive prompt on its own.
  Accepts an injectable `PinChallengeIo` for tests that exercise
  the challenge without a real TTY.
- `MODE_ENV_VAR` — the env-var name (`VIUR_TESTING_MODE`) for
  workers to branch on.

See the [`@spltz/viur-testing` README](https://github.com/sprengplatz/viur-testing/blob/main/playwright/README.md)
for the full TypeScript surface.
