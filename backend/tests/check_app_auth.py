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

    # The repo's `permissions` field reflects classic collaborator roles
    # (admin/push/pull), which GitHub only populates for user-authenticated
    # tokens — it's always False for App installation tokens regardless of
    # what's actually granted. The real grant lives on the installation
    # object itself, fetched here with the App JWT (not the installation token).
    async with app._client(app.app_jwt()) as client:
        resp = await client.get(f"/app/installations/{installation_id}")
        resp.raise_for_status()

    print("Auth works. Installation permissions:", resp.json()["permissions"])


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: check_app_auth.py <owner/repo> <installation_id>")
    asyncio.run(main(sys.argv[1], int(sys.argv[2])))
