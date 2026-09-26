"""Manual check: does the configured GitHub App actually authenticate against a real repo?

Not part of the automated suite — pytest only collects test_*.py, so this needs a live
GITHUB_APP_ID + private key in backend/.env and hits the real GitHub API. Run directly:

    uv run python tests/check_app_auth.py <owner/repo> <installation_id>

Find <installation_id> at https://github.com/settings/installations (click into the App;
it's the number in the URL).
"""

import asyncio
import sys

from services.github_app import get_github_app


async def main(repo: str, installation_id: int) -> None:
    app = get_github_app()
    if app is None:
        raise SystemExit("GITHUB_APP_ID / private key not configured in backend/.env")

    async with await app.installation_client(installation_id) as client:
        resp = await client.get(f"/repos/{repo}")
        resp.raise_for_status()

    print("Auth works. Repo permissions:", resp.json()["permissions"])


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: check_app_auth.py <owner/repo> <installation_id>")
    asyncio.run(main(sys.argv[1], int(sys.argv[2])))
