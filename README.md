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

The backend reaches a user's CI through a **GitHub App** installed on their repo.

| Endpoint | Called by | Purpose |
|---|---|---|
| `POST /api/webhooks/github` | GitHub App webhook | Receives `workflow_run` events (flow below) |
| `POST /api/webhooks/junit` | You / other CI systems | Hand in JUnit XML directly, skipping the GitHub rerun |

Both endpoints require an `X-Hub-Signature-256` HMAC of the body, keyed with `GITHUB_WEBHOOK_SECRET`. Both reply `202` with `{action, reason, thread_id}`.

**Flow**
1. A workflow listed in `WATCHED_WORKFLOWS` fails. The backend dispatches the user's **Flaky Rerun** workflow on the default branch, passing the failing commit.
2. The Flaky Rerun runs the test suite `RERUN_ATTEMPTS` times in parallel and uploads one JUnit artifact per attempt.
3. When it completes, the backend downloads those artifacts, plus the original run's `junit*` artifact as attempt 0. It turns them into per-test pass/fail counts (`rerun_results`) and runs the LangGraph graph with `thread_id` = the original run id. The monitoring dashboard shows the result.

### GitHub App setup
1. Create the App under **Settings → Developer settings → GitHub Apps**:
   - **Webhook URL:** `https://<public backend URL>/api/webhooks/github`. For local development, use a tunnel such as `cloudflared tunnel --url http://localhost:8000`.
   - **Webhook secret:** the same value as `GITHUB_WEBHOOK_SECRET`.
   - **Repository permissions:** Actions *read & write*, Contents *read*, Metadata *read*.
   - **Subscribe to events:** Workflow run.
2. Generate a private key and save it as `backend/github-app.pem`. `*.pem` is git-ignored.
3. Fill in `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY_PATH`, `GITHUB_WEBHOOK_SECRET` and `WATCHED_WORKFLOWS` in `backend/.env` (see `.env.example`).
4. Install the App on the repo you want to watch.

### Rerun workflow contract (in the user's repo)
The backend relies on this contract:
- The workflow is named **`Flaky Rerun`** and lives at `.github/workflows/flaky-rerun.yml` **on the default branch**.
- It is triggered by `workflow_dispatch` with the string inputs `original_run_id`, `head_sha` and `attempts`.
- `run-name` contains `#<original_run_id>`, which is how the result is matched to the failed run.
- Each attempt uploads an artifact named **`junit-attempt-<n>`** containing JUnit XML.

A pytest example:

```yaml
name: Flaky Rerun
run-name: "Flaky Rerun #${{ inputs.original_run_id }}"

on:
  workflow_dispatch:
    inputs:
      original_run_id: { required: true, type: string }
      head_sha: { required: true, type: string }
      attempts: { required: false, type: string, default: "10" }

jobs:
  plan:
    runs-on: ubuntu-latest
    outputs:
      attempts: ${{ steps.matrix.outputs.attempts }}
    steps:
      - id: matrix
        env:
          ATTEMPTS: ${{ inputs.attempts }}
        run: python3 -c 'import json, os; print("attempts=" + json.dumps(list(range(1, int(os.environ["ATTEMPTS"]) + 1))))' >> "$GITHUB_OUTPUT"

  rerun:
    needs: plan
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        attempt: ${{ fromJSON(needs.plan.outputs.attempts) }}
    steps:
      - uses: actions/checkout@v7
        with:
          ref: ${{ inputs.head_sha }}
      - uses: actions/setup-python@v7
        with:
          python-version: "3.13"
      - run: pip install -r requirements.txt
      - run: python -m pytest --junitxml=junit/report.xml
        continue-on-error: true
      - uses: actions/upload-artifact@v7
        if: always()
        with:
          name: junit-attempt-${{ matrix.attempt }}
          path: junit/
```

We recommend that the regular CI workflow also writes JUnit XML and uploads it on failure, as an artifact whose name starts with `junit` (for example `junit-results`). That report counts as attempt 0. Without it, a test that failed in CI but passes every rerun leaves no evidence.

Other frameworks only change the test step. The parser reads any JUnit XML:

| Runner | Produce JUnit XML with |
|---|---|
| Maven Surefire / Gradle | On by default (`target/surefire-reports`, `build/test-results`) |
| pytest | `--junitxml=junit/report.xml` |
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