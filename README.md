# Flaky Debug Agent

A CI/CD automation system that debugs flaky-based deployments. 
External system that relies on Github Actions. 
The goal of the system is to determine if the failure is a flaky-based error. 
If it is not then call Bob for fixing instantly. 
Else run through check test for possible root causes in the Git Diffs then Modularity of the feature.

## Todo
- [ ] Handle deploy.yml
- [ ] Endpoint utk dihit + callback
- [ ] LangGraph
- [ ] Monitoring dashboard
- [ ] Agent + Tools


## Submission
- [ ] Short Description
- [ ] Long Description
- [ ] IBM Bob Usage Statement
- [ ] Video presentation
- [ ] Slide presentation
- [ ] Cover image

## Flow (Mermaid)
```mermaid
flowchart TD
    Start([Start])
    End([End])

    InputData[/Input: Receive GitHub Payload & Logs/]
    OutputData[/Output: Generate Docs and place them in the codebase/]

    CheckFail{Did CI\nFail?}
    Test100x[Run Parallel Retest 10x in Sandbox with pytest]
    CheckFlaky{Is the Test\nFlaky?}
    MultiAgent[Multi-Agent System]
    CodeFixing[Code Fixing]
    Retest10x[Retest 10x]
    CheckPass{Does it Pass\n100%?}

    Start --> InputData
    InputData --> CheckFail

    CheckFail -- No --> End
    CheckFail -- Yes --> Test100x

    Test100x --> CheckFlaky
    CheckFlaky -- No --> End
    CheckFlaky -- Yes --> MultiAgent

    MultiAgent --> CodeFixing
    CodeFixing --> Retest10x
    Retest10x --> CheckPass

    CheckPass -- No --> End
    CheckPass -- Yes --> OutputData
    OutputData --> End
```

## GitHub integration

The backend reaches a user's CI with a **personal access token** (`GITHUB_TOKEN`) and learns about CI runs through a **repo webhook**. A GitHub App will replace the PAT later; `services/github_app.py` is ready for that but isn't wired up yet.

| Endpoint | Called by | Purpose |
|---|---|---|
| `POST /api/webhooks/github` | Repo webhook (`workflow_run` events) | Starts the flaky rerun, then the analysis once the rerun is done |
| `POST /api/webhooks/junit` | You / other CI systems | Hand in JUnit XML directly, skipping the GitHub rerun |

Both endpoints require an `X-Hub-Signature-256` HMAC of the body, keyed with `GITHUB_WEBHOOK_SECRET`, and reply `202` with `{action, reason, thread_id}`. The actual work runs in the background, because it takes far longer than GitHub's 10-second webhook timeout.

**Flow**
1. **Phase A.** A workflow listed in `WATCHED_WORKFLOWS` fails. The backend reads that run's JUnit artifact to find the failing tests. It then dispatches **Flaky Rerun** with `purpose=detect` on the default branch, for the failing commit.
2. Flaky Rerun runs those tests `RERUN_ATTEMPTS` times (default 5) in parallel, each on a fresh VM, and uploads `rerun-attempt-<n>` artifacts.
3. **Phase B.** When the detect rerun completes, the backend downloads its artifacts, plus the original run's JUnit report as attempt 0. It turns them into per-test pass/fail counts (`rerun_results`) and runs the LangGraph graph with `thread_id` = the original run id. The monitoring dashboard shows the result.
4. **Retest.** The graph's `retest_flaky` node dispatches Flaky Rerun again with `purpose=retest` to verify the fix, and waits for the result itself. The webhook ignores retest runs, so they can't start a new analysis.

### Setup
1. **Token.** Create a fine-grained PAT for the watched repo with:
   - **Actions: read & write**, to dispatch reruns and download artifacts;
   - **Contents: read & write**, to clone and to push the fix branch.

   Put it in `GITHUB_TOKEN` in `backend/.env`.
2. **Webhook.** In the repo, go to **Settings → Webhooks → Add webhook**:
   - **Payload URL:** `https://<public backend URL>/api/webhooks/github`. For local development, use a tunnel such as `cloudflared tunnel --url http://localhost:8000`.
   - **Content type:** `application/json`.
   - **Secret:** the same value as `GITHUB_WEBHOOK_SECRET`.
   - **Events:** only **Workflow runs**.
3. **Rerun workflow.** Copy `backend/templates/flaky-rerun.yml` to `.github/workflows/flaky-rerun.yml` on the repo's **default branch**.
4. **JUnit from CI.** Make the regular CI workflow write JUnit XML and upload it as an artifact when it fails (example below). Phase A reads the failing tests from that artifact. Without it, nothing gets rerun.
5. **Settings.** Set `WATCHED_WORKFLOWS` (e.g. `["CI"]`) and `RERUN_ATTEMPTS` in `backend/.env` (see `.env.example`).

Example CI steps for pytest:

```yaml
      - run: python -m pytest -o junit_family=xunit1 --junitxml=junit/report.xml
      - uses: actions/upload-artifact@v7
        if: failure()
        with:
          name: junit-results
          path: junit/
```

`-o junit_family=xunit1` records each test's file, so the backend gets exact pytest node IDs such as `tests/test_cart.py::TestCart::test_add`. Without it, IDs are a best guess, and the guess is wrong for tests inside classes.

### Flaky Rerun contract
`backend/templates/flaky-rerun.yml` is the reference. The backend relies on the following:
- **Name and location:** the workflow is named `Flaky Rerun` and lives on the default branch.
- **Inputs:** `workflow_dispatch` takes `sha`, `test_ids` (a JSON list of pytest node IDs), `framework`, `attempts`, `original_run_id` and `purpose` (`detect` or `retest`).
- **Run name:** `run-name: "Flaky Rerun (<purpose>) #<original_run_id> @ <sha>"`. This is how the backend finds the run it dispatched and tells detect runs from retest runs. It must match `parse_rerun_title` in `services/github_dispatch.py`, and a test checks that it does.
- **Artifacts:** one per attempt, named `rerun-attempt-<n>`, containing JUnit XML.

The template only runs pytest for now. The parser already reads JUnit XML from every runner below, so supporting another framework only means changing the template's install and test steps:

| Runner | Produce JUnit XML with |
|---|---|
| Maven Surefire / Gradle | On by default (`target/surefire-reports`, `build/test-results`) |
| pytest | `-o junit_family=xunit1 --junitxml=junit/report.xml` |
| Jest | `npm i -D jest-junit` and add it as a reporter |
| Vitest | `--reporter=junit --outputFile=junit/report.xml` |
| Go | `gotestsum --junitfile junit/report.xml` |
| RSpec | `rspec_junit_formatter` gem, `--format RspecJunitFormatter` |
| .NET | `JunitXml.TestLogger` NuGet package, or `trx2junit` |

### Testing locally without GitHub
Start the backend. The app lifespan needs Postgres (`docker compose up -d` in `backend/`); then run `uv run backend`. Post signed JUnit XML to `/api/webhooks/junit`. `reports` maps attempt number to a list of XML strings:

```bash
BODY='{"repository":"octocat/Hello-World","run_id":"local-1","reports":{"0":["<testsuite><testcase classname=\"t\" name=\"a\"><failure/></testcase></testsuite>"],"1":["<testsuite><testcase classname=\"t\" name=\"a\"/></testsuite>"]}}'
SIG="sha256=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$GITHUB_WEBHOOK_SECRET" | awk '{print $NF}')"
curl -X POST http://localhost:8000/api/webhooks/junit \
  -H "Content-Type: application/json" -H "X-Hub-Signature-256: $SIG" -d "$BODY"
```

The run then appears in `GET /api/runs` and on the dashboard.