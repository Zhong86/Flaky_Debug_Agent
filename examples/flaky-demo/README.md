# flaky-demo

A tiny shop service whose test suite is **flaky**: one test fails about half the time, even though nothing about the code changes between runs. It's the demo target for the [Flaky Debug Agent](https://github.com/Zhong86/Flaky_Debug_Agent).

## What happens on a push to `main`

1. **Deploy** (`.github/workflows/deploy.yml`) runs the tests. If they pass, the `deploy` job ships to the `production` environment (a mock step). If they fail, the deploy is skipped and the JUnit report is uploaded as the `junit-results` artifact.
2. GitHub notifies the Flaky Debug Agent through the repo webhook. The agent reads the failing tests from `junit-results` and dispatches **Flaky Rerun** (`.github/workflows/flaky-rerun.yml`), which reruns just those tests 5 times in parallel.
3. The agent classifies the result. A test that both passed and failed is flaky, so IBM Bob investigates, fixes the code on a `flaky-fix/…` branch, and the fix is retested the same way.
4. Every step shows up on the agent's dashboard.

The "Deploy" workflow is manually re-runnable (**Actions → Deploy → Run workflow**), because the flaky test passes about half the time.

## Running the tests locally

```bash
pip install -r requirements.txt
python -m pytest
```

Run it a few times: sometimes everything passes, sometimes `test_concurrent_orders_each_take_an_item` fails.

## Connecting it to the agent

Setup (public repo, access token, webhook) is described in the agent repo's `deploy/README.md`. Keep `.github/workflows/flaky-rerun.yml` identical to the agent's `backend/templates/flaky-rerun.yml`: the agent parses that workflow's run names.
