"""Framework-agnostic JUnit XML → per-test pass/fail tallies (`rerun_results`).

Every runner we support ends up emitting JUnit XML (natively or via a reporter):
Maven Surefire / Gradle, pytest `--junitxml`, jest-junit, Vitest `--reporter=junit`,
gotestsum, rspec_junit_formatter and JunitXml.TestLogger. They all share `<testcase>`
elements whose `<failure>` / `<error>` / `<skipped>` children carry the outcome, so a
single walk over `testcase` elements handles all of them regardless of how the
`<testsuites>` / `<testsuite>` wrappers are nested.

Test IDs are pytest node IDs for pytest reports — flaky-rerun.yml feeds them straight
back to `pytest`, and the investigator agent reads the file part — and
`classname::name` for every other framework.
"""

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import TypedDict
from xml.etree.ElementTree import Element, ParseError

from defusedxml import ElementTree as SafeElementTree
from defusedxml.common import DefusedXmlException

logger = logging.getLogger(__name__)

_FAILED = ("failure", "error")
# Maven Surefire records in-run retries (rerunFailingTestsCount) as extra children:
# each one is an execution that failed before the final outcome.
_SUREFIRE_RETRIES = ("flakyFailure", "flakyError", "rerunFailure", "rerunError")

_MAX_MESSAGES_PER_TEST = 5
_MAX_MESSAGE_CHARS = 1_500

Reports = Mapping[int, Sequence[bytes | str]]


class RerunResult(TypedDict):
    """Matches `RerunResult` in frontend/src/lib/types.ts, plus failure messages for the agent."""

    test_id: str
    attempts: int
    passed: int
    failed: int
    messages: list[str]


@dataclass
class _Tally:
    executions: int = 0
    failures: int = 0
    messages: list[str] = field(default_factory=list)


def _local(tag: str) -> str:
    """Drop an XML namespace prefix: `{urn:x}testcase` → `testcase`."""
    return tag.rsplit("}", 1)[-1]


def _pytest_node_id(case: Element, is_pytest: bool) -> str | None:
    classname = (case.get("classname") or "").strip()
    name = (case.get("name") or "").strip()
    path = (case.get("file") or "").strip().replace("\\", "/").removeprefix("./")
    if path.endswith(".py"):
        # xunit1 (`-o junit_family=xunit1`) records the file, so the node ID is exact:
        # classname "tests.test_cart.TestCart" + file "tests/test_cart.py"
        # → "tests/test_cart.py::TestCart::test_add". Classes are whatever follows the
        # module's own name in classname, however much package prefix precedes it.
        parts = classname.split(".")
        stem = PurePosixPath(path).stem
        classes = parts[parts.index(stem) + 1 :] if stem in parts else []
        return "::".join([path, *classes, name])
    if is_pytest and classname:
        # pytest's default xunit2 omits the file: best-effort module path, right for
        # module-level test functions, wrong for tests inside a class.
        return f"{classname.replace('.', '/')}.py::{name}"
    return None


def _test_id(case: Element, is_pytest: bool) -> str:
    if node_id := _pytest_node_id(case, is_pytest):
        return node_id
    classname = (case.get("classname") or "").strip()
    name = (case.get("name") or "").strip()
    return f"{classname}::{name}" if classname else name


def _message(element: Element, attempt: int) -> str:
    text = " ".join(filter(None, [element.get("message"), "".join(element.itertext()).strip()]))
    return f"[attempt {attempt}] {text}".rstrip()[:_MAX_MESSAGE_CHARS]


def _parse_report(report: bytes | str) -> Element | None:
    try:
        return SafeElementTree.fromstring(report)
    except (ParseError, DefusedXmlException) as exc:
        logger.warning("Skipping unreadable JUnit report: %s", exc)
        return None


def _elements(root: Element, tag: str) -> Iterable[Element]:
    return (element for element in root.iter() if _local(element.tag) == tag)


def _tally(reports: Reports) -> dict[str, _Tally]:
    tallies: dict[str, _Tally] = {}
    for attempt, attempt_reports in sorted(reports.items()):
        for report in attempt_reports:
            root = _parse_report(report)
            if root is None:
                continue
            is_pytest = any(s.get("name") == "pytest" for s in _elements(root, "testsuite"))
            for case in _elements(root, "testcase"):
                children = [child for child in case if isinstance(child.tag, str)]
                tags = [_local(child.tag) for child in children]
                if "skipped" in tags and not any(tag in _FAILED for tag in tags):
                    continue

                tally = tallies.setdefault(_test_id(case, is_pytest), _Tally())
                retries = [c for c, t in zip(children, tags) if t in _SUREFIRE_RETRIES]
                final_failures = [c for c, t in zip(children, tags) if t in _FAILED]

                tally.executions += 1 + len(retries)
                tally.failures += len(retries) + (1 if final_failures else 0)
                for failed in [*retries, *final_failures]:
                    if len(tally.messages) < _MAX_MESSAGES_PER_TEST:
                        tally.messages.append(_message(failed, attempt))
    return tallies


def parse_junit_results(reports: Reports) -> list[RerunResult]:
    """Aggregate JUnit reports, grouped by attempt number, into per-test tallies.

    Every executed test is included — a fully green retest must still produce
    results for `retest_flaky` to call it passed. Skipped testcases don't count.
    """
    results = [
        RerunResult(
            test_id=test_id,
            attempts=tally.executions,
            passed=tally.executions - tally.failures,
            failed=tally.failures,
            messages=tally.messages,
        )
        for test_id, tally in _tally(reports).items()
    ]
    return sorted(results, key=lambda r: (-r["failed"], r["test_id"]))


def parse_failed_test_ids(reports: Reports) -> list[str]:
    """IDs of the tests that failed at least once — what flaky-rerun.yml gets to rerun."""
    return sorted(test_id for test_id, tally in _tally(reports).items() if tally.failures)


def failure_log(results: Sequence[RerunResult], limit: int = 20_000) -> str:
    """Readable summary of the failures, used as the graph state's `logs`."""
    lines: list[str] = []
    for result in results:
        if not result["failed"]:
            continue
        lines.append(
            f"FAILED {result['test_id']} ({result['failed']}/{result['attempts']} runs failed)"
        )
        lines.extend(f"    {message}" for message in result["messages"])
    return "\n".join(lines)[:limit]
