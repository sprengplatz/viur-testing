/**
 * Auto-detect of run mode for ``createGlobalSetup``.
 *
 * Single entry point :func:`detectMode` does:
 *
 * 1. Probe ``POST /json/_test/config/status`` via
 *    :func:`probeStatusEndpoint`.
 * 2. **HTTP 200 + validated test-mode payload** → ``{ mode: "test",
 *    status }``. The status carries the session token and is the
 *    same shape that ``requireTestMode`` would have returned, so
 *    downstream code paths are unchanged.
 * 3. **Any 4xx** → run the PIN challenge; on success return
 *    ``{ mode: "guarded" }``; on failure the challenge throws and
 *    the suite never starts. The whole 4xx range counts because
 *    ViUR's JSON renderer answers unknown modules with 401 rather
 *    than 404 (permission-check runs before route resolution), so
 *    treating only 404 as ``unarmed`` would never trip Guarded Mode
 *    on a ViUR backend.
 * 4. **Anything else** (5xx, timeout, 200-but-malformed,
 *    integrity-check failure, …) → throw straight from
 *    :func:`probeStatusEndpoint`. Auto-detect never silently falls
 *    back to Guarded Mode on an ambiguous server state — that would
 *    defeat the PIN gate.
 */

import {
  type RequireTestModeOptions,
  type ServerStatus,
  probeStatusEndpoint,
} from "./test-mode.js"
import { runPinChallenge, type PinChallengeIo } from "./pin-challenge.js"

export type DetectedMode =
  | { mode: "test"; status: ServerStatus }
  | { mode: "guarded" }

export interface DetectModeOptions extends RequireTestModeOptions {
  /** PIN-challenge I/O override (used only in tests). */
  _pinIo?: PinChallengeIo
  /** PIN value override (used only in tests; production generates fresh). */
  _pin?: string
}

/**
 * Probe the backend, decide the mode, and on Guarded Mode run the
 * interactive PIN challenge before returning.
 *
 * Returns once the suite is allowed to start. Throws if the server
 * is in an ambiguous state, or if the PIN challenge fails.
 */
export async function detectMode(opts: DetectModeOptions): Promise<DetectedMode> {
  const probe = await probeStatusEndpoint(opts)
  if (probe.kind === "armed") {
    return { mode: "test", status: probe.status }
  }
  await runPinChallenge({
    backendUrl: opts.backendUrl,
    io: opts._pinIo,
    _pin: opts._pin,
  })
  return { mode: "guarded" }
}
