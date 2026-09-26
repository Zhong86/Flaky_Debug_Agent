# Running the Flaky Debug Agent on your own machine

This folder runs the whole system (API, graph, IBM Bob, database and dashboard) on one always-on PC and publishes it at a stable public URL through ngrok. GitHub sends its webhooks to that URL, and anyone can open the dashboard there while the PC is running.

```
GitHub webhook / browser → ngrok (your static domain) → caddy
    /api/*  → backend   FastAPI + LangGraph + git + IBM Bob Shell
    /*      → frontend  Next.js monitoring dashboard
backend → postgres (run history for the dashboard)
```

Only ngrok is reachable from the internet. Postgres, the backend and the dashboard have no published ports.

## What you need

- **The PC:** Docker Desktop (Windows/macOS) or Docker Engine with the compose plugin (Linux), plus Git. **8 GB RAM or more**: IBM Bob Shell alone needs 4 GB.
- **ngrok account (free):** copy your authtoken, and claim your free static domain under *Domains* (something like `your-name.ngrok-free.app`).
- **IBM Bob API key** with *Inference* scope, from the Bob web portal.
- **The demo repo** on GitHub, created in step 3 from `examples/flaky-demo/`. It must be **public**, because the agent clones it without credentials.
- **GitHub fine-grained personal access token**, with *Repository access* set to the demo repo only, and these permissions:
  - Actions: read & write (dispatch reruns, download test reports)
  - Contents: read & write (push Bob's fix branch)
  - Metadata: read

## 1. Start the stack

From the repo root:

```bash
cp deploy/.env.example deploy/.env     # then fill it in
docker compose -f deploy/compose.yaml up -d --build
```

The first build takes a few minutes: it installs Python and Node dependencies and IBM Bob Shell. The build fails if `bob` doesn't install.

## 2. Check it

- `https://<your-domain>/api/health` returns `{"status":"ok"}`.
- `https://<your-domain>/` shows the dashboard. ngrok shows a one-time "You are about to visit…" page in each browser; click through.
- Check that Bob Shell accepts the flags the agents use:

  ```bash
  docker compose -f deploy/compose.yaml exec backend bob --version
  docker compose -f deploy/compose.yaml exec backend bob run --help
  ```

  `graph/tools.py` calls `bob run --mode … --workspace … --format json --accept-license [--team-id …]`. If `--help` doesn't list one of these, tell the agent owners before the live demo.

## 3. Create the demo repo and its webhook

1. On GitHub, create an **empty public** repository, for example `flaky-demo`. Don't add a README.
2. In that repo, go to **Settings → Webhooks → Add webhook**:
   - **Payload URL:** `https://<your-domain>/api/webhooks/github`
   - **Content type:** `application/json`
   - **Secret:** the value of `GITHUB_WEBHOOK_SECRET` in `deploy/.env`
   - **Events:** *Let me select individual events* → only **Workflow runs**

   GitHub sends a `ping` right away. It should show a green `202` under *Recent Deliveries*.
3. Push the demo code. The first push already runs the **Deploy** workflow:

   ```bash
   cp -r examples/flaky-demo ../flaky-demo && cd ../flaky-demo
   git init -b main && git add . && git commit -m "Flaky demo"
   git remote add origin https://github.com/<you>/flaky-demo.git
   git push -u origin main
   ```

## 4. Watch a run

- **Actions tab:** *Deploy* runs the tests. The concurrency test fails about half the time, and when it does, `deploy` is skipped. If it passed, re-roll with **Actions → Deploy → Run workflow**.
- **Webhook deliveries** (or the ngrok inspector at `http://localhost:4040` on the PC). You should see:
  1. `rerun_scheduled`, when Deploy fails.
  2. A **Flaky Rerun (detect)** run in Actions that repeats the failing test 5 times.
  3. `analysis_scheduled`, when that rerun completes.
  4. Later, a **Flaky Rerun (retest)** run to verify Bob's fix. Its delivery is `ignored` on purpose, because the graph waits for it directly.
- **Dashboard:** a row appears for the failed Deploy run. Open it to follow each graph step: flaky verdict, Bob's findings, the fix branch (`flaky-fix/…` in the demo repo), the retest and the report.

## Operating it

| Task | Command (from the repo root) |
|---|---|
| Follow the backend logs | `docker compose -f deploy/compose.yaml logs -f backend` |
| Restart after editing `deploy/.env` | `docker compose -f deploy/compose.yaml up -d` |
| Update to the latest code | `git pull && docker compose -f deploy/compose.yaml up -d --build` |
| Stop (keeps data) | `docker compose -f deploy/compose.yaml down` |
| Back up the run history | `docker compose -f deploy/compose.yaml exec postgres pg_dump -U postgres flaky_debug > backup.sql` |

Run history and bug reports live in the `pgdata` and `reports` Docker volumes, so they survive restarts and rebuilds. `down -v` deletes them.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Delivery `401 Invalid webhook signature` | The webhook secret on GitHub doesn't match `GITHUB_WEBHOOK_SECRET`. |
| Delivery `503 … is not configured` | `GITHUB_WEBHOOK_SECRET` or `GITHUB_TOKEN` is empty in `deploy/.env`. |
| Delivery `202` with `"action": "ignored"` | Normal for runs the agent doesn't act on. The `reason` says why (e.g. workflow not in `WATCHED_WORKFLOWS`). |
| `rerun_scheduled` but no Flaky Rerun appears | Check the backend logs. A 404 on dispatch means `.github/workflows/flaky-rerun.yml` is missing from the demo repo's default branch; a 403 means the token lacks *Actions: write*. |
| Deliveries time out | The stack or the ngrok container isn't running: `docker compose -f deploy/compose.yaml ps`. |
| Graph steps show `[bobshell error]` | `BOB_API_KEY` is missing or invalid (general-type keys also need `BOB_TEAM_ID`). |

## Security notes

- **Bob executes code from the watched repo.** Its agent mode edits and runs commands inside the cloned demo repo, inside the backend container, as a non-root user, with no Docker socket and no host folders mounted. Keep the token scoped to the demo repo only.
- **The dashboard and `/api/runs` have no login.** Anyone with the URL can read run history and Bob's findings. That's fine for a demo; add authentication before pointing this at private code. The webhook endpoints are protected by their signature.
- **Stopping everything:** `docker compose -f deploy/compose.yaml down` takes the public URL offline.
