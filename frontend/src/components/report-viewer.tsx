"use client";

import { useEffect, useState } from "react";

import { ApiError, getRunReport } from "@/lib/api";
import { Mono } from "./ui";

/** Renders inline `**bold**` spans within a line of markdown text. */
function InlineMarkdown({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return (
    <>
      {parts.map((part, i) =>
        part.startsWith("**") && part.endsWith("**") ? (
          <strong key={i}>{part.slice(2, -2)}</strong>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}

/**
 * Minimal markdown-to-JSX renderer for the stub reports `documents` writes
 * (headings + plain paragraphs). Not a general-purpose parser.
 */
function MarkdownBody({ content }: { content: string }) {
  const lines = content.split("\n");
  return (
    <div className="space-y-2 text-sm leading-relaxed text-ink-soft">
      {lines.map((line, i) => {
        if (line.startsWith("### ")) {
          return (
            <h3 key={i} className="mt-3 text-sm font-semibold text-ink">
              <InlineMarkdown text={line.slice(4)} />
            </h3>
          );
        }
        if (line.startsWith("## ")) {
          return (
            <h2 key={i} className="mt-4 text-base font-semibold text-ink">
              <InlineMarkdown text={line.slice(3)} />
            </h2>
          );
        }
        if (line.startsWith("# ")) {
          return (
            <h1 key={i} className="text-lg font-semibold text-ink">
              <InlineMarkdown text={line.slice(2)} />
            </h1>
          );
        }
        if (line.trim() === "") {
          return <div key={i} className="h-1" />;
        }
        return (
          <p key={i}>
            <InlineMarkdown text={line} />
          </p>
        );
      })}
    </div>
  );
}

export function ReportViewer({ threadId, documentPath }: { threadId: string; documentPath: string }) {
  const [open, setOpen] = useState(false);
  // Stays mounted after the first open so the close transition can play instead
  // of the panel just vanishing.
  const [everOpened, setEverOpened] = useState(false);
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState<Error | null>(null);
  // No separate "loading" state — content/error start null and the first
  // successful or failed fetch fills one of them in; see usePoll for the same idea.
  const loading = open && content === null && error === null;

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    getRunReport(threadId, { signal: controller.signal })
      .then((text) => {
        setContent(text);
        setError(null);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(err instanceof Error ? err : new Error(String(err)));
      });
    return () => controller.abort();
  }, [open, threadId]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open]);

  const show = () => {
    setEverOpened(true);
    setOpen(true);
  };

  return (
    <>
      <button
        type="button"
        onClick={show}
        className="cursor-pointer rounded text-left text-accent underline decoration-dotted underline-offset-2 hover:text-accent-strong hover:decoration-solid"
      >
        <Mono>{documentPath}</Mono>
      </button>

      {everOpened ? (
        <div className="fixed inset-0 z-50" aria-hidden={!open}>
          <div
            className={`absolute inset-0 bg-black/40 transition-opacity duration-200 ${
              open ? "opacity-100" : "pointer-events-none opacity-0"
            }`}
            onClick={() => setOpen(false)}
          />
          <div
            className="absolute top-0 right-0 flex h-full w-full max-w-xl flex-col border-l border-line bg-surface shadow-xl transition-transform duration-300 ease-out"
            style={{ transform: open ? "translateX(0)" : "translateX(100%)" }}
          >
            <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
              <p className="truncate font-mono text-xs text-ink-muted">{documentPath}</p>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="rounded px-2 py-1 text-xs font-medium text-ink-muted hover:bg-surface-raised hover:text-ink"
              >
                Close
              </button>
            </div>
            <div className="overflow-auto p-4">
              {loading ? <p className="text-sm text-ink-muted">Loading report…</p> : null}
              {error ? (
                <p className="text-sm text-red-600 dark:text-red-400">
                  {error instanceof ApiError && error.status === 404
                    ? "Report file not found."
                    : `Failed to load report: ${error.message}`}
                </p>
              ) : null}
              {content !== null && !error ? <MarkdownBody content={content} /> : null}
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
