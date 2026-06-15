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

/**
 * Shared mutable holder so the configureServer plugin can write the
 * token once at startup and every proxyReq event handler can read it
 * synchronously (http-proxy events are not async-aware). The holder
 * also carries the backend URL because the proxy-side refresh hook
 * (triggered on observed 403s, see :func:`withTokenInjection`) needs
 * to know where to POST.
 */
const tokenHolder: {
  value: string | null
  backendUrl: string | null
  fetching: boolean
  lastFetchAt: number
} = {
  value: null,
  backendUrl: null,
  fetching: false,
  lastFetchAt: 0,
}

const DEFAULT_BACKEND_URL = "http://localhost:8080"

/**
 * Default TTL for background refresh, in milliseconds. After this
 * many ms, the next proxy request opportunistically triggers a
 * fresh token fetch in the background — protects against the case
 * where another runner ended the session via ``/finish``, after
 * which the cached token starts producing 403s indefinitely.
 *
 * Picked at one hour: short enough that a stale token is corrected
 * within a single working session, long enough that a healthy
 * session does not waste roundtrips. Override via
 * :func:`viurTestingTokenFetch`'s ``refreshIntervalMs`` option.
 */
const DEFAULT_REFRESH_INTERVAL_MS = 60 * 60 * 1000

/**
 * Fetch the session token from ``/json/_test/config/status`` and
 * write it into the shared holder. Idempotent — the ``fetching``
 * flag short-circuits parallel calls (proxyReq is sync; a 403 in
 * one request may overlap with another's TTL timer triggering
 * another fetch).
 */
async function refreshToken(backendUrl: string): Promise<void> {
  if (tokenHolder.fetching) return
  tokenHolder.fetching = true
  try {
    const resp = await fetch(`${backendUrl}/json/_test/config/status`, { method: "POST" })
    if (!resp.ok) {
      console.warn(
        `[viur-testing] could not (re)fetch token: ${resp.status} ${resp.statusText} — ` +
          `is the backend running with VIUR_TESTING=test? Proxy will keep ` +
          `using the previously cached token (if any).`,
      )
      return
    }
    const data = (await resp.json()) as { token: string; namespace?: string | null }
    if (typeof data.token === "string" && data.token.length > 0) {
      tokenHolder.value = data.token
      tokenHolder.lastFetchAt = Date.now()
    }
  } catch (err) {
    console.warn(
      `[viur-testing] could not (re)fetch token from ${backendUrl}: ${(err as Error).message}. ` +
        `Proxy will keep using the previously cached token (if any).`,
    )
  } finally {
    tokenHolder.fetching = false
  }
}

export interface ViurTestingTokenFetchOptions {
  /** Base URL of the running ViUR backend. Default: http://localhost:8080. */
  backendUrl?: string
  /**
   * Background-refresh interval in milliseconds. After this many ms
   * since the last successful fetch, the next proxy request triggers
   * a fresh fetch in the background. Default:
   * :data:`DEFAULT_REFRESH_INTERVAL_MS` (1 hour). Set to ``0`` to
   * disable TTL-based refresh (403-based refresh stays active).
   */
  refreshIntervalMs?: number
}

/**
 * Vite plugin that fetches the test session token at server start
 * and caches it for the proxy entries produced by
 * {@link withTokenInjection}.
 *
 * The cached token is **refreshed automatically** when:
 *
 * - A proxied backend response comes back with HTTP 403 — this is
 *   the symptom of another runner having ended the session via
 *   ``/_test/config/finish`` while this Vite session was running.
 *   The next proxied request after the refresh will carry the new
 *   token.
 * - More than ``refreshIntervalMs`` (default: 1 hour) have passed
 *   since the last successful fetch. A long-running ``vite dev``
 *   session would otherwise hold the original token indefinitely.
 *
 * Both refresh paths are best-effort: they trigger a background
 * fetch and let the *next* request pick up the result. The request
 * that triggered the refresh still carries the old token (the
 * proxy can't await an async fetch on a sync event).
 */
export function viurTestingTokenFetch(opts: ViurTestingTokenFetchOptions = {}): Plugin {
  const backendUrl = opts.backendUrl ?? DEFAULT_BACKEND_URL
  return {
    name: "viur-testing:token-fetch",
    async configureServer() {
      tokenHolder.backendUrl = backendUrl
      await refreshToken(backendUrl)
      if (tokenHolder.value) {
        console.log(
          `[viur-testing] proxy will inject ${TOKEN_HEADER} on every backend call. ` +
            `Token will be refreshed on observed 403s or after ` +
            `${opts.refreshIntervalMs ?? DEFAULT_REFRESH_INTERVAL_MS}ms idle.`,
        )
      }
    },
  }
}

/** Build a Vite proxy entry that injects the test token on every forwarded request. */
export function withTokenInjection(target: string, opts: ViurTestingTokenFetchOptions = {}): ProxyOptions {
  const refreshIntervalMs = opts.refreshIntervalMs ?? DEFAULT_REFRESH_INTERVAL_MS
  return {
    target,
    changeOrigin: false,
    configure: (proxy) => {
      proxy.on("proxyReq", (proxyReq) => {
        // TTL-based refresh: kick off in the background if the token
        // is older than the threshold. Disabled with refreshIntervalMs=0.
        if (
          refreshIntervalMs > 0
          && tokenHolder.backendUrl
          && Date.now() - tokenHolder.lastFetchAt > refreshIntervalMs
        ) {
          // Fire-and-forget; the next request gets the fresh token.
          refreshToken(tokenHolder.backendUrl).catch(() => {})
        }
        if (tokenHolder.value) {
          proxyReq.setHeader(TOKEN_HEADER, tokenHolder.value)
        }
      })
      proxy.on("proxyRes", (proxyRes) => {
        // 403-based refresh: another runner may have finished the
        // session in between; refresh so the *next* request gets a
        // valid token. The current request is already lost — the 403
        // propagates to the browser unchanged.
        if (proxyRes.statusCode === 403 && tokenHolder.backendUrl) {
          refreshToken(tokenHolder.backendUrl).catch(() => {})
        }
      })
    },
  }
}
