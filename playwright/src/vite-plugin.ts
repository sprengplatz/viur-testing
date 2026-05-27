/**
 * Vite plugin + proxy helpers for transparent test-mode aware dev servers.
 *
 * When an engineer opens the dev server in a browser themselves (no
 * Playwright), the browser does NOT carry `X-Viur-Test-Token`. Every
 * backend call would be answered with 403 by viur-testing's
 * TokenValidator. This plugin makes the Vite proxy a transparent
 * test-mode adapter:
 *
 *   1. `viurTestingTokenFetch()` runs once at Vite server start. It
 *      POSTs `/json/_test/config/status`, caches the session token.
 *   2. `withTokenInjection(target)` builds a Vite proxy entry whose
 *      `proxyReq` handler stamps `X-Viur-Test-Token` on every
 *      forwarded request.
 *
 * Typical wiring:
 *
 *     import { defineConfig } from "vite"
 *     import { viurTestingTokenFetch, withTokenInjection } from "@spltz/viur-testing"
 *
 *     const BACKEND = "http://localhost:8080"
 *
 *     export default defineConfig({
 *       plugins: [viurTestingTokenFetch({ backendUrl: BACKEND })],
 *       server: {
 *         proxy: {
 *           "/vi/": withTokenInjection(BACKEND),
 *           "/json": withTokenInjection(BACKEND),
 *           // …
 *         },
 *       },
 *     })
 *
 * The Vue/React app and the human in the browser do not need to know
 * the token exists.
 */

import type { Plugin, ProxyOptions } from "vite"

import { TOKEN_HEADER } from "./test-mode.js"

// Shared mutable holder so the configureServer plugin can write the
// token once at startup and every proxyReq event handler can read it
// synchronously (http-proxy events are not async-aware).
const tokenHolder: { value: string | null } = { value: null }

export interface ViurTestingTokenFetchOptions {
  /** Base URL of the running ViUR backend. Default: http://localhost:8080. */
  backendUrl?: string
}

/**
 * Vite plugin that fetches the test session token at server start
 * and caches it for the proxy entries produced by {@link withTokenInjection}.
 */
export function viurTestingTokenFetch(opts: ViurTestingTokenFetchOptions = {}): Plugin {
  const backendUrl = opts.backendUrl ?? "http://localhost:8080"
  return {
    name: "viur-testing:token-fetch",
    async configureServer() {
      try {
        const resp = await fetch(`${backendUrl}/json/_test/config/status`, { method: "POST" })
        if (!resp.ok) {
          console.warn(
            `[viur-testing] could not fetch token: ${resp.status} ${resp.statusText} — ` +
              `is the backend running with VIUR_TESTING_ENABLE=1? Proxy will pass ` +
              `requests through without the ${TOKEN_HEADER} header (expect 403s).`,
          )
          return
        }
        const data = (await resp.json()) as { token: string; namespace: string | null }
        tokenHolder.value = data.token
        console.log(
          `[viur-testing] proxy will inject ${TOKEN_HEADER} on every backend call ` +
            `(namespace=${data.namespace ?? "(default)"})`,
        )
      } catch (err) {
        console.warn(
          `[viur-testing] could not fetch token from ${backendUrl}: ${(err as Error).message}. ` +
            `Is the backend up? Proxy will pass requests through without the token header.`,
        )
      }
    },
  }
}

/** Build a Vite proxy entry that injects the test token on every forwarded request. */
export function withTokenInjection(target: string): ProxyOptions {
  return {
    target,
    changeOrigin: false,
    configure: (proxy) => {
      proxy.on("proxyReq", (proxyReq) => {
        if (tokenHolder.value) {
          proxyReq.setHeader(TOKEN_HEADER, tokenHolder.value)
        }
      })
    },
  }
}
