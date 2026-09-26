import pytest

from graph.nodes import check_flaky
from services.junit import failure_log, parse_failed_test_ids, parse_junit_results
from tests.helpers import junit


def _by_id(results: list) -> dict:
    return {r["test_id"]: (r["attempts"], r["passed"], r["failed"]) for r in results}


@pytest.mark.parametrize(
    ("fixture", "failing_test_id", "passing_test_id"),
    [
        (
            "pytest.xml",
            "tests/test_inventory.py::test_concurrent_reserve",
            "tests/test_inventory.py::test_single_reserve",
        ),
        (
            "jest.xml",
            "cart adds items concurrently::cart adds items concurrently",
            "cart removes items::cart removes items",
        ),
        (
            "vitest.xml",
            "src/queue.test.ts::queue > drains in order",
            "src/queue.test.ts::queue > starts empty",
        ),
        (
            "gotestsum.xml",
            "example.com/shop/worker::TestPoolDrain",
            "example.com/shop/worker::TestPoolStart",
        ),
        (
            "rspec.xml",
            "spec.models.order_spec::Order#total sums line items concurrently",
            "spec.models.order_spec::Order#total is zero when empty",
        ),
        (
            "dotnet.xml",
            "Shop.Tests.InventoryTests::ReserveIsAtomic",
            "Shop.Tests.InventoryTests::ReserveSingle",
        ),
    ],
)
def test_each_framework_reports_every_executed_test(
    fixture: str, failing_test_id: str, passing_test_id: str
) -> None:
    results = parse_junit_results({1: [junit(fixture)]})

    assert _by_id(results) == {failing_test_id: (1, 0, 1), passing_test_id: (1, 1, 0)}
    assert results[0]["test_id"] == failing_test_id  # failures sort first
    assert results[0]["messages"][0].startswith("[attempt 1] ")


def test_pytest_xunit1_reports_give_exact_node_ids() -> None:
    ids = set(_by_id(parse_junit_results({1: [junit("pytest_xunit1.xml")]})))

    assert ids == {
        "tests/test_cart.py::TestCart::test_add[2-3]",
        "tests/test_cart.py::test_empty",
        # classname rooted elsewhere than the file path still resolves via the file stem
        "tests/test_checkout.py::test_pay",
    }


def test_surefire_in_run_retries_count_as_extra_executions() -> None:
    results = _by_id(parse_junit_results({1: [junit("surefire.xml")]}))

    # flakyFailure = failed once, then passed on Surefire's own retry
    assert results["com.example.CacheTest::concurrentWrite"] == (2, 1, 1)
    # failure + rerunFailure = failed both times
    assert results["com.example.CacheTest::readAfterWrite"] == (2, 0, 2)
    assert results["com.example.CacheTest::evict"] == (1, 1, 0)


def test_skipped_tests_are_left_out() -> None:
    ids = set(_by_id(parse_junit_results({1: [junit("pytest.xml")], 2: [junit("gotestsum.xml")]})))

    assert "tests/test_inventory.py::test_windows_only" not in ids
    assert "example.com/shop/worker::TestPoolWindows" not in ids


def test_counts_aggregate_across_attempts_and_feed_check_flaky() -> None:
    reports = {
        0: [junit("pytest.xml")],  # the original CI failure
        1: [junit("pytest_passing.xml")],
        2: [junit("pytest.xml")],
        3: [junit("pytest_passing.xml")],
    }

    results = parse_junit_results(reports)

    assert _by_id(results) == {
        "tests/test_inventory.py::test_concurrent_reserve": (4, 2, 2),
        "tests/test_inventory.py::test_single_reserve": (4, 4, 0),
    }
    assert [m.split("]")[0] for m in results[0]["messages"]] == ["[attempt 0", "[attempt 2"]
    # The graph's check_flaky node reads exactly this shape.
    assert check_flaky({"rerun_results": results}) == {"is_flaky": True}


def test_always_failing_test_is_not_flaky() -> None:
    reports = {attempt: [junit("pytest.xml")] for attempt in range(1, 4)}

    results = parse_junit_results(reports)

    assert _by_id(results)["tests/test_inventory.py::test_concurrent_reserve"] == (3, 0, 3)
    assert check_flaky({"rerun_results": results}) == {"is_flaky": False}


def test_fully_green_retest_still_returns_results() -> None:
    results = parse_junit_results({1: [junit("pytest_passing.xml")]})

    # retest_flaky: bool(results) and all(passed == attempts)
    assert results and all(r["passed"] == r["attempts"] for r in results)


def test_failed_test_ids_are_deduplicated_across_files_and_attempts() -> None:
    reports = {0: [junit("pytest.xml"), junit("pytest.xml")], 1: [junit("pytest.xml")]}

    assert parse_failed_test_ids(reports) == ["tests/test_inventory.py::test_concurrent_reserve"]
    assert parse_failed_test_ids({0: [junit("pytest_passing.xml")]}) == []


def test_messages_are_capped_per_test() -> None:
    reports = {attempt: [junit("pytest.xml")] for attempt in range(1, 11)}

    failing = parse_junit_results(reports)[0]

    assert failing["failed"] == 10
    assert len(failing["messages"]) == 5


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

    ids = set(_by_id(parse_junit_results(reports)))

    assert ids == {
        "Shop.Tests.InventoryTests::ReserveIsAtomic",
        "Shop.Tests.InventoryTests::ReserveSingle",
    }


def test_failure_log_summarises_only_failing_tests() -> None:
    results = parse_junit_results({1: [junit("pytest.xml")], 2: [junit("pytest_passing.xml")]})

    log = failure_log(results)

    assert log.startswith(
        "FAILED tests/test_inventory.py::test_concurrent_reserve (1/2 runs failed)"
    )
    assert "AssertionError: assert 7 == 10" in log
    assert "test_single_reserve" not in log
    assert len(failure_log(results, limit=20)) == 20
