"""examples/flaky-demo — the watched repo of the deployed demo — must fit the backend."""

import json
from pathlib import Path

import yaml
from dotenv import dotenv_values

from services import github_artifacts
from services.github_dispatch import RERUN_WORKFLOW_FILE
from tests.helpers import FakeGitHub, make_zip

REPO_ROOT = Path(__file__).parents[2]
DEMO = REPO_ROOT / "examples" / "flaky-demo"
WORKFLOWS = DEMO / ".github" / "workflows"


def _deploy_workflow() -> dict:
    return yaml.safe_load((WORKFLOWS / "deploy.yml").read_text())


def _junit_upload_step() -> dict:
    steps = _deploy_workflow()["jobs"]["test"]["steps"]
    [upload] = [s for s in steps if "upload-artifact" in s.get("uses", "")]
    return upload


def test_demo_carries_the_current_rerun_template() -> None:
    template = REPO_ROOT / "backend" / "templates" / RERUN_WORKFLOW_FILE

    assert (WORKFLOWS / RERUN_WORKFLOW_FILE).read_text() == template.read_text()


def test_deploy_workflow_is_watched_by_the_deployed_stack() -> None:
    env = dotenv_values(REPO_ROOT / "deploy" / ".env.example")

    assert _deploy_workflow()["name"] in json.loads(env["WATCHED_WORKFLOWS"])


def test_deploy_only_runs_after_the_tests_pass() -> None:
    assert _deploy_workflow()["jobs"]["deploy"]["needs"] == "test"


def test_ci_writes_xunit1_junit_and_uploads_it_on_failure() -> None:
    steps = _deploy_workflow()["jobs"]["test"]["steps"]
    commands = " ".join(step.get("run", "") for step in steps)

    assert "-o junit_family=xunit1" in commands  # exact pytest node IDs
    assert "--junitxml=junit/report.xml" in commands
    assert _junit_upload_step()["if"] == "failure()"
    assert _junit_upload_step()["with"]["path"] == "junit/report.xml"


async def test_ci_report_counts_as_the_original_attempt(fake_github: FakeGitHub) -> None:
    artifact_name = _junit_upload_step()["with"]["name"]
    fake_github.add_artifact(111, artifact_name, make_zip({"report.xml": b"<testsuite/>"}))

    reports = await github_artifacts.download_run_artifacts("acme/flaky-demo", 111)

    assert list(reports) == [0]


def test_demo_installs_the_way_flaky_rerun_expects() -> None:
    # flaky-rerun.yml runs `pip install -r requirements.txt` then `pytest <node ids>`
    # from the repo root.
    requirements = (DEMO / "requirements.txt").read_text()

    assert "pytest" in requirements
    assert (DEMO / "pytest.ini").is_file()
