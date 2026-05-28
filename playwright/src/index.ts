/**
 * Public surface of @spltz/viur-testing.
 *
 * Spec authors typically only need `test` + `expect` + the test-module
 * helpers; playwright.config.ts uses the global-setup/teardown
 * factories; the Vite plugin lives next to them so a single import
 * source can cover both runtime contexts.
 */

export {
  TOKEN_HEADER,
  requireTestMode,
  probeStatusEndpoint,
  finishTestMode,
  authenticatedApi,
  type ServerStatus,
  type RequireTestModeOptions,
  type StatusProbeResult,
} from "./test-mode.js"

export {
  detectMode,
  type DetectedMode,
  type DetectModeOptions,
} from "./mode-detect.js"

export {
  runPinChallenge,
  defaultPinChallengeIo,
  type PinChallengeIo,
  type RunPinChallengeOptions,
} from "./pin-challenge.js"

export {
  test,
  expect,
  type TestModeFixtures,
} from "./fixtures.js"

export {
  callTestModule,
  callTestModuleRaw,
  type TestModuleResult,
} from "./test-modules.js"

export { assertNoDirectPlaywrightImports } from "./forbidden-imports.js"

export {
  createGlobalSetup,
  MODE_ENV_VAR,
  type GlobalSetupOptions,
} from "./global-setup.js"

export {
  createGlobalTeardown,
  type GlobalTeardownOptions,
} from "./global-teardown.js"

export {
  viurTestingTokenFetch,
  withTokenInjection,
  type ViurTestingTokenFetchOptions,
} from "./vite-plugin.js"
