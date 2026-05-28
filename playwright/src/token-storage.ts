/**
 * Internal helper: one canonical location for the runner-side token
 * persistence file.
 *
 * The Playwright globalSetup writes the parsed `/json/_test/config/status`
 * payload here; the per-test fixtures (`fixtures.ts`) and the test-module
 * helper (`test-modules.ts`) read it back. Hard-coded on purpose — when
 * the path was configurable on the setup side but not on the fixture
 * side, customising one half silently broke the other half.
 *
 * The location is resolved at call time (not at module load) so a host
 * that changes `process.cwd()` between globalSetup and worker start
 * (rare, but possible with weird launchers) ends up with the same path
 * everywhere.
 */

import { resolve } from "node:path"

/** Relative directory the file lives in, off of `process.cwd()`. */
export const TOKEN_FILE_DIR = ".auth"

/** File name inside :data:`TOKEN_FILE_DIR`. */
export const TOKEN_FILE_NAME = "token.json"

/**
 * Absolute path to the persisted server-status file, resolved against
 * the current working directory.
 */
export function tokenFilePath(): string {
  return resolve(process.cwd(), TOKEN_FILE_DIR, TOKEN_FILE_NAME)
}
