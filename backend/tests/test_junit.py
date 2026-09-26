import pytest

from graph.nodes import check_flaky
from services.junit import failure_log, parse_junit_results
from tests.helpers import junit


@pytest.mark.parametrize(
    ("fixture", "failing_test_id"),
    [
        ("pytest.xml", "tests.test_inventory::test_concurrent_reserve"),
        ("jest.xml", "cart adds items concurrently::cart adds items concurrently"),
        ("vitest.xml", "src/queue.test.ts::queue > drains in order"),
        ("gotestsum.xml", "example.com/shop/worker::TestPoolDrain"),
        ("rspec.xml", "spec.models.order_spec::Order#total sums line items concurrently"),
        ("dotnet.xml", "Shop.Tests.InventoryTests::ReserveIsAtomic"),
    ],
)
def test_each_framework_reports_only_its_failing_test(fixture: str, failing_test_id: str) -> None:
    [result] = parse_junit_results({1: [junit(fixture)]})

    assert result["test_id"] == failing_test_id
    assert (result["attempts"], result["passed"], result["failed"]) == (1, 0, 1)
    assert result["messages"][0].startswith("[attempt 1] ")


def test_surefire_in_run_retries_count_as_extra_executions() -> None:
    results = {r["test_id"]: r for r in parse_junit_results({1: [junit("surefire.xml")]})}

    # flakyFailure = failed once, then passed on Surefire's own retry
    flaky = results["com.example.CacheTest::concurrentWrite"]
    assert (flaky["attempts"], flaky["passed"], flaky["failed"]) == (2, 1, 1)
    # failure + rerunFailure = failed both times
    broken = results["com.example.CacheTest::readAfterWrite"]
    assert (broken["attempts"], broken["passed"], broken["failed"]) == (2, 0, 2)
    assert "com.example.CacheTest::evict" not in results


def test_skipped_and_passing_tests_are_left_out() -> None:
    test_ids = {r["test_id"] for r in parse_junit_results({1: [junit("pytest.xml")]})}

    assert test_ids == {"tests.test_inventory::test_concurrent_reserve"}


def test_counts_aggregate_across_attempts_and_feed_check_flaky() -> None:
    reports = {
        0: [junit("pytest.xml")],  # the original CI failure
        1: [junit("pytest_passing.xml")],
        2: [junit("pytest.xml")],
        3: [junit("pytest_passing.xml")],
    }

    [result] = parse_junit_results(reports)

    assert (result["attempts"], result["passed"], result["failed"]) == (4, 2, 2)
    assert [m.split("]")[0] for m in result["messages"]] == ["[attempt 0", "[attempt 2"]
    # The teammates' graph node reads exactly this shape.
    assert check_flaky({"rerun_results": [result]}) == {"is_flaky": True}


def test_always_failing_test_is_not_flaky() -> None:
    reports = {attempt: [junit("pytest.xml")] for attempt in range(1, 4)}

    [result] = parse_junit_results(reports)

    assert (result["attempts"], result["passed"], result["failed"]) == (3, 0, 3)
    assert check_flaky({"rerun_results": [result]}) == {"is_flaky": False}


def test_passing_reruns_alone_produce_no_results() -> None:
    assert parse_junit_results({1: [junit("pytest_passing.xml")]}) == []


def test_messages_are_capped_per_test() -> None:
    reports = {attempt: [junit("pytest.xml")] for attempt in range(1, 11)}

    [result] = parse_junit_results(reports)

    assert result["failed"] == 10
    assert len(result["messages"]) == 5


def test_reports_from_several_files_and_frameworks_combine() -> None:
    results = parse_junit_results({1: [junit("jest.xml"), junit("gotestsum.xml")]})

    assert len(results) == 2


def test_string_reports_and_namespaced_tags_are_accepted() -> None:
    namespaced = (
        '<ns:testsuite xmlns:ns="urn:x"><ns:testcase classname="a" name="b">'
        '<ns:error message="boom"/></ns:testcase></ns:testsuite>'
    )

    [result] = parse_junit_results({1: [namespaced]})

    assert result["test_id"] == "a::b"
    assert result["messages"] == ["[attempt 1] boom"]


def test_unreadable_reports_are_skipped() -> None:
    billion_laughs = (
        '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
        '<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>'
        "<testsuite><testcase name='x'><failure>&lol2;</failure></testcase></testsuite>"
    )
    reports = {1: [b"<testsuite><testcase", billion_laughs.encode(), junit("dotnet.xml")]}

    [result] = parse_junit_results(reports)

    assert result["test_id"] == "Shop.Tests.InventoryTests::ReserveIsAtomic"


def test_failure_log_summarises_each_failing_test() -> None:
    results = parse_junit_results({1: [junit("pytest.xml")], 2: [junit("pytest_passing.xml")]})

    log = failure_log(results)

    assert log.startswith("FAILED tests.test_inventory::test_concurrent_reserve (1/2 runs failed)")
    assert "AssertionError: assert 7 == 10" in log
    assert len(failure_log(results, limit=20)) == 20
