"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type PollState<T> = {
  data: T | null;
  error: Error | null;
  /** True only on the very first load, so refreshes don't blank the screen. */
  loading: boolean;
  lastUpdated: string | null;
  refresh: () => void;
};

/**
 * Re-runs `fetcher` on an interval and keeps the last good value on screen while
 * refreshing. Pass `intervalMs = null` to fetch once and stop (used to pause live
 * updates). The fetcher is held in a ref so callers can pass an inline closure
 * without restarting the timer on every render.
 */
export function usePoll<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  intervalMs: number | null,
): PollState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  const fetcherRef = useRef(fetcher);
  // Synced in an effect rather than during render; this effect is declared first so
  // the ref is current before the polling effect below can fire.
  useEffect(() => {
    fetcherRef.current = fetcher;
  }, [fetcher]);

  const refresh = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let cancelled = false;

    const run = async () => {
      try {
        const result = await fetcherRef.current(controller.signal);
        if (cancelled) return;
        setData(result);
        setError(null);
        setLastUpdated(new Date().toISOString());
      } catch (err) {
        // An abort is us tearing down, not a failure worth surfacing.
        if (cancelled || controller.signal.aborted) return;
        setError(err instanceof Error ? err : new Error(String(err)));
      } finally {
        if (!cancelled) {
          setLoading(false);
          // Chain the next tick only after this one settles, so a slow or failing
          // backend can't pile up overlapping requests.
          if (intervalMs !== null) timer = setTimeout(run, intervalMs);
        }
      }
    };

    void run();

    return () => {
      cancelled = true;
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [intervalMs, nonce]);

  return { data, error, loading, lastUpdated, refresh };
}
