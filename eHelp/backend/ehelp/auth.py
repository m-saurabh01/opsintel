from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from ehelp.config import Config


@dataclass(frozen=True)
class User:
    user_id: str
    name: str
    groups: tuple[str, ...]

    @property
    def is_admin(self) -> bool:
        return "admin" in self.groups

    def public(self) -> dict:
        return {"user_id": self.user_id, "name": self.name, "groups": list(self.groups), "is_admin": self.is_admin}


ANONYMOUS = User("", "", ())


def user_from_headers(request: Request, config: Config) -> User:
    """Identity comes from the front-end gateway headers iv-user, iv-groups and iv-name.

    The app must only be reachable through that gateway, otherwise the headers could be forged.
    """
    headers = request.headers
    user_id = headers.get("iv-user", "").strip()
    if not user_id:
        return User("dev", "Developer", ("user", "admin")) if config.dev_admin else ANONYMOUS
    groups = tuple(g.strip().lower() for g in headers.get("iv-groups", "").split(",") if g.strip())
    return User(user_id, headers.get("iv-name", "").strip() or user_id, groups)


def current_user(request: Request) -> User:
    return user_from_headers(request, request.app.state.config)


def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Administrator access required")
    return user
