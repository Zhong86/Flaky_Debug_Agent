import type { RunSummary, RunTimeline } from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api";

/** Carries the HTTP status so callers can tell "no such run" from "backend is down". */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });

  if (!res.ok) {
    throw new ApiError(`API ${path} failed: ${res.status} ${res.statusText}`, res.status);
  }

  return (await res.json()) as T;
}

export async function listRuns(limit = 50, init?: RequestInit): Promise<RunSummary[]> {
  const { runs } = await apiFetch<{ runs: RunSummary[] }>(`/runs?limit=${limit}`, init);
  return runs;
}

export function getRunTimeline(threadId: string, init?: RequestInit): Promise<RunTimeline> {
  return apiFetch<RunTimeline>(`/runs/${encodeURIComponent(threadId)}`, init);
}

export async function getRunReport(threadId: string, init?: RequestInit): Promise<string> {
  const path = `/runs/${encodeURIComponent(threadId)}/report`;
  const res = await fetch(`${API_BASE_URL}${path}`, init);

  if (!res.ok) {
    throw new ApiError(`API ${path} failed: ${res.status} ${res.statusText}`, res.status);
  }

  return res.text();
}
