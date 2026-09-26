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

The backend reaches a user's CI either through a **GitHub App** (`services/github_app.py`) — one App installed on any number of repos, each webhook delivery carrying an `installation.id` that's exchanged for a short-lived installation token — or, as a fallback, a **personal access token** (`GITHUB_TOKEN`) plus a **repo webhook**. The App is preferred whenever `GITHUB_APP_ID` is set; the PAT is used for calls with no installation context (the JUnit ingest endpoint) or when no App is configured at all.

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

### Deployment and demo
- **[`deploy/`](deploy/README.md)** runs the whole stack on one machine with Docker Compose: API, graph, IBM Bob, Postgres and dashboard, published at a stable URL through ngrok. Its runbook covers the setup below end to end.
- **[`examples/flaky-demo/`](examples/flaky-demo/README.md)** is the watched repo for the demo: a small service with a genuinely flaky async test, a `deploy.yml` pipeline (test, then deploy) and `flaky-rerun.yml`. Push it as its own public GitHub repo.

### Setup

#### Option A: GitHub App (recommended)

1. **Create the App.** On GitHub, go to **Settings → Developer settings → GitHub Apps → New GitHub App** (for a personal App) or your organization's equivalent page. Fill in:
   - **GitHub App name:** anything unique, e.g. `flaky-debug-agent-<you>`.
   - **Homepage URL:** your repo's URL (or the deployed dashboard's).
   - **Webhook → Active**, checked.
     - **Webhook URL:** `https://<public backend URL>/api/webhooks/github`. For local dev, tunnel with `cloudflared tunnel --url http://localhost:8000` first.
     - **Webhook secret:** generate one (e.g. `openssl rand -hex 32`) — this becomes `GITHUB_WEBHOOK_SECRET`.
   - **Permissions → Repository permissions:**
     - **Actions:** Read and write (dispatch reruns, download artifacts).
     - **Contents:** Read and write (clone, and push the fix branch).
     - **Metadata:** Read-only (already required).
   - **Subscribe to events:** check **Workflow run**.
   - **Where can this GitHub App be installed?:** "Only on this account" is fine unless you need it on other orgs too.
   - Click **Create GitHub App**.
2. **Generate a private key.** On the App's page, scroll to **Private keys → Generate a private key**. GitHub downloads a `.pem` file — save it somewhere outside version control, e.g. `backend/secrets/github-app.pem` (already gitignored), and never paste its contents into chat, a PR, or a log.
3. **Note the App ID**, shown near the top of the same page.
4. **Install the App.** Go to **Install App** in the sidebar, pick your account/org, and choose the repo(s) to watch (the demo repo, or your own).
5. **Configure the backend.** In `backend/.env`:
   ```
   GITHUB_APP_ID=<the App ID>
   GITHUB_APP_PRIVATE_KEY_PATH=/absolute/path/to/github-app.pem
   GITHUB_WEBHOOK_SECRET=<the webhook secret from step 1>
   ```
6. **Rerun workflow.** Copy `backend/templates/flaky-rerun.yml` to `.github/workflows/flaky-rerun.yml` on the watched repo's **default branch**.
7. **JUnit from CI.** Make the regular CI workflow write JUnit XML and upload it as an artifact when it fails (example below). Phase A reads the failing tests from that artifact. Without it, nothing gets rerun.
8. **Settings.** Set `WATCHED_WORKFLOWS` (e.g. `["CI"]`) and `RERUN_ATTEMPTS` in `backend/.env` (see `.env.example`).

Since the App's webhook is configured once on the App itself, installing it on more repos later needs no extra webhook setup — just **Install App → Configure** to add repos.

#### Option B: personal access token (no App)

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