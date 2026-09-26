"""Framework-agnostic JUnit XML → `rerun_results` for the graph's `check_flaky` node.

Every runner we support ends up emitting JUnit XML (natively or via a reporter):
Maven Surefire / Gradle, pytest `--junitxml`, jest-junit, Vitest `--reporter=junit`,
gotestsum, rspec_junit_formatter and JunitXml.TestLogger. They all share `<testcase>`
elements whose `<failure>` / `<error>` / `<skipped>` children carry the outcome, so a
single walk over `testcase` elements handles all of them regardless of how the
`<testsuites>` / `<testsuite>` wrappers are nested.
"""

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
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


def _test_id(case: Element) -> str:
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


def _testcases(root: Element) -> Iterable[Element]:
    return (element for element in root.iter() if _local(element.tag) == "testcase")


def parse_junit_results(attempts: Mapping[int, Sequence[bytes | str]]) -> list[RerunResult]:
    """Aggregate JUnit reports grouped by attempt number into per-test pass/fail counts.

    Only tests that failed at least once are returned — those are the only ones
    `check_flaky` can call flaky, and it keeps the checkpointed graph state small.
    Skipped testcases don't count as executions.
    """
    tallies: dict[str, _Tally] = {}

    for attempt, reports in sorted(attempts.items()):
        for report in reports:
            root = _parse_report(report)
            if root is None:
                continue
            for case in _testcases(root):
                children = [child for child in case if isinstance(child.tag, str)]
                tags = [_local(child.tag) for child in children]
                if "skipped" in tags and not any(tag in _FAILED for tag in tags):
                    continue

                tally = tallies.setdefault(_test_id(case), _Tally())
                retries = [c for c, t in zip(children, tags) if t in _SUREFIRE_RETRIES]
                final_failures = [c for c, t in zip(children, tags) if t in _FAILED]

                tally.executions += 1 + len(retries)
                tally.failures += len(retries) + (1 if final_failures else 0)
                for failed in [*retries, *final_failures]:
                    if len(tally.messages) < _MAX_MESSAGES_PER_TEST:
                        tally.messages.append(_message(failed, attempt))

    results = [
        RerunResult(
            test_id=test_id,
            attempts=tally.executions,
            passed=tally.executions - tally.failures,
            failed=tally.failures,
            messages=tally.messages,
        )
        for test_id, tally in tallies.items()
        if tally.failures
    ]
    return sorted(results, key=lambda r: (-r["failed"], r["test_id"]))


def failure_log(results: Sequence[RerunResult], limit: int = 20_000) -> str:
    """Readable summary of the failures, used as the graph state's `logs`."""
    lines: list[str] = []
    for result in results:
        lines.append(
            f"FAILED {result['test_id']} ({result['failed']}/{result['attempts']} runs failed)"
        )
        lines.extend(f"    {message}" for message in result["messages"])
    return "\n".join(lines)[:limit]
