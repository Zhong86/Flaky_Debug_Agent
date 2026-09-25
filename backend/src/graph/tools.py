"""
tools.py — Language-agnostic tool functions for the Flaky Debug Agent.

Read-only tools  (safe for the Explore / Investigator sub-agents):
  • run_generic_test      — run any test command N times via a subprocess loop
                           and return a statistical failure-rate summary.
  • filter_async_git_diff — extract concurrency-related hunks from git diff
                           (supports Python, Java, Node.js, Go, and more).
  • read_source_code      — read and return the raw text of any source file.

Write tools  (reserved for the General / Fixer sub-agent):
  • write_fixed_code      — overwrite a file with corrected source code.
  • create_markdown_docs  — write a timestamped markdown bug-report to disk.
"""

from __future__ import annotations

import shlex
import subprocess
import textwrap
from datetime import datetime
from pathlib import Path

from langchain_core.tools import tool

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Multi-language concurrency keywords that flag a diff hunk as suspicious.
# Covers: Python, Java, Node.js / TypeScript, Go, C#, Ruby, Rust, and Shell.
_ASYNC_THREAD_PATTERNS = (
    # ---- Python ----
    "async def",
    "await ",
    "asyncio",
    "threading",
    "ThreadPoolExecutor",
    "concurrent.futures",
    "loop.run_until_complete",
    "create_task",
    "gather(",
    # ---- Java ----
    "synchronized",
    "Runnable",
    "java.util.concurrent",
    "ExecutorService",
    "CountDownLatch",
    "ReentrantLock",
    "volatile ",
    # ---- Go ----
    "goroutine",
    "go func",
    "chan ",
    "sync.Mutex",
    "sync.WaitGroup",
    "select {",
    # ---- JavaScript / TypeScript / Node.js ----
    "Promise",
    "async function",
    "async () =>",
    ".then(",
    "setTimeout(",
    "setInterval(",
    "process.nextTick",
    "new Worker(",
    # ---- Generic / cross-language ----
    "Thread(",
    "async ",        # catches C#, Kotlin, Dart, etc.
    "await ",        # intentional duplicate — belt-and-suspenders for JS/C#
    "lock ",
    "lock(",
    "Lock()",
    "sleep(",        # race-condition indicator in any language
    "Semaphore(",
    "Mutex",
    "atomic",
    "volatile",
)

# Where markdown reports land (relative to project root).
_REPORT_DIR = Path(__file__).parents[3] / "flaky_debug"


# ---------------------------------------------------------------------------
# Read-only tools
# ---------------------------------------------------------------------------


@tool
def run_generic_test(repo_path: str, test_command: str, iterations: int = 10) -> dict:
    """Run *test_command* inside *repo_path* exactly *iterations* times.

    Each run is independent — no plugin required.  Works for any language:
    ``npm test``, ``mvn test``, ``go test ./...``, ``pytest``, etc.

    Returns a dict with:
      - ``iterations``     (int)   — number of runs requested.
      - ``failures``       (int)   — number of runs that exited non-zero.
      - ``failure_rate``   (float) — failures / iterations (0.0 – 1.0).
      - ``flaky``          (bool)  — True when 0 < failure_rate < 1.0
                                     (i.e. the test *sometimes* fails).
      - ``always_fails``   (bool)  — True when every run failed (likely a
                                     deterministic bug, not flakiness).
      - ``run_outputs``    (list)  — [{returncode, stdout, stderr}] per run.
    """
    args = shlex.split(test_command)
    run_outputs: list[dict] = []
    failures = 0

    for _ in range(iterations):
        proc = subprocess.run(
            args,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=300,
        )
        run_outputs.append(
            {
                "returncode": proc.returncode,
                "stdout": proc.stdout[-4000:],   # cap at 4 kB to stay within LLM context
                "stderr": proc.stderr[-2000:],
            }
        )
        if proc.returncode != 0:
            failures += 1

    failure_rate = failures / iterations if iterations > 0 else 0.0
    return {
        "iterations": iterations,
        "failures": failures,
        "failure_rate": round(failure_rate, 4),
        "flaky": 0 < failure_rate < 1.0,
        "always_fails": failures == iterations,
        "run_outputs": run_outputs,
    }


@tool
def filter_async_git_diff(repo_path: str) -> str:
    """Return the subset of the latest git diff that touches concurrency code.

    Runs ``git diff HEAD~1 HEAD`` and filters to hunks that contain any
    concurrency-related keyword across Python, Java, Go, Node.js, and more.
    Returns the filtered diff text, or an empty string if nothing is found.
    """
    result = subprocess.run(
        ["git", "diff", "HEAD~1", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode != 0:
        return f"[git diff error]\n{result.stderr}"

    diff_text = result.stdout
    relevant_lines: list[str] = []
    in_relevant_hunk = False

    for line in diff_text.splitlines(keepends=True):
        if line.startswith("@@"):
            # New hunk boundary — reset and re-evaluate from this line.
            in_relevant_hunk = False
        if any(pat in line for pat in _ASYNC_THREAD_PATTERNS):
            in_relevant_hunk = True
        if in_relevant_hunk:
            relevant_lines.append(line)

    return "".join(relevant_lines)


@tool
def read_source_code(file_path: str) -> str:
    """Read and return the raw text of *file_path*.

    Language-agnostic — works for Python, Java, JavaScript, Go, etc.
    Returns the file contents as a plain string, or an error message if the
    file cannot be read.
    """
    try:
        return Path(file_path).read_text(encoding="utf-8")
    except OSError as exc:
        return f"[read error] {exc}"


# ---------------------------------------------------------------------------
# Write tools
# ---------------------------------------------------------------------------


@tool
def write_fixed_code(file_path: str, new_code: str) -> str:
    """Overwrite *file_path* with *new_code*.

    Returns a confirmation string with the number of lines written.
    """
    path = Path(file_path)
    path.write_text(new_code, encoding="utf-8")
    line_count = new_code.count("\n") + 1
    return f"Written {line_count} lines to {file_path}"


@tool
def create_markdown_docs(content: str) -> str:
    """Write *content* as a timestamped markdown bug-report.

    The file is placed under ``flaky_debug/reports/`` relative to the project
    root.  Returns the absolute path of the written file.
    """
    report_dir = _REPORT_DIR / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = report_dir / f"bug_report_{timestamp}.md"

    header = textwrap.dedent(f"""\
        # Flaky Debug — Bug Report
        **Generated:** {datetime.now().isoformat()}

        ---

        """)
    filepath.write_text(header + content, encoding="utf-8")
    return str(filepath)
