from dataclasses import dataclass

import httpx

from opsintel.config import Settings


class GiteaError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GiteaRepo:
    id: int
    full_name: str
    clone_url: str
    default_branch: str
    private: bool
    empty: bool
    archived: bool


def _repo(d: dict) -> GiteaRepo:
    return GiteaRepo(
        id=d["id"], full_name=d["full_name"], clone_url=d["clone_url"], default_branch=d.get("default_branch") or "",
        private=bool(d.get("private")), empty=bool(d.get("empty")), archived=bool(d.get("archived")),
    )


class GiteaClient:
    def __init__(self, settings: Settings, timeout: float = 15.0):
        if not settings.gitea_url:
            raise GiteaError("GITEA_URL is not configured")
        token = settings.gitea_token.get_secret_value()
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"token {token}"
        self._client = httpx.Client(base_url=settings.gitea_url.rstrip("/") + "/api/v1", headers=headers,
                                    timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GiteaClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _get(self, path: str, **params) -> httpx.Response:
        try:
            res = self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise GiteaError(f"Gitea request failed: {exc}") from exc
        if res.status_code == 404:
            raise GiteaError(f"not found: {path}")
        if res.status_code >= 400:
            raise GiteaError(f"Gitea returned {res.status_code} for {path}")
        return res

    def version(self) -> str:
        return self._get("/version").json().get("version", "")

    def current_user(self) -> dict:
        return self._get("/user").json()

    def get_repo(self, full_name: str) -> GiteaRepo:
        owner, _, name = full_name.partition("/")
        if not owner or not name or "/" in name:
            raise GiteaError(f"invalid repository name '{full_name}', expected owner/name")
        return _repo(self._get(f"/repos/{owner}/{name}").json())

    def list_repos(self, page_size: int = 50) -> list[GiteaRepo]:
        repos, page = [], 1
        while True:
            body = self._get("/repos/search", limit=page_size, page=page).json()
            batch = body.get("data", [])
            repos.extend(_repo(d) for d in batch)
            if len(batch) < page_size:
                return repos
            page += 1

    def ensure_push_hook(self, full_name: str, url: str, secret: str) -> tuple[int, bool]:
        """Create a push webhook for `url` unless one already exists. Returns (hook_id, created)."""
        owner, _, name = full_name.partition("/")
        for hook in self._get(f"/repos/{owner}/{name}/hooks").json():
            if hook.get("config", {}).get("url") == url:
                return hook["id"], False
        try:
            res = self._client.post(f"/repos/{owner}/{name}/hooks", json={
                "type": "gitea", "active": True, "events": ["push"], "branch_filter": "*",
                "config": {"url": url, "content_type": "json", "secret": secret},
            })
        except httpx.HTTPError as exc:
            raise GiteaError(f"Gitea request failed: {exc}") from exc
        if res.status_code >= 400:
            raise GiteaError(f"creating webhook failed ({res.status_code}): {res.text[:300]}")
        return res.json()["id"], True
