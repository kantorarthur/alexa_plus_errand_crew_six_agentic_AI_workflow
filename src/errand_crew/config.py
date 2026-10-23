"""Runtime settings, read from environment variables."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

MIN_TOKEN_LENGTH = 24
MAX_CLIENTS = 10
CLIENT_NAME_RE = re.compile(r"^[a-z0-9_-]{1,32}$")


def validate_client_tokens(tokens: dict[str, str]) -> None:
    """One secret per client. Error messages never contain a secret."""
    if not tokens:
        raise ValueError("ERRAND_CREW_TOKENS must define at least one client")
    if len(tokens) > MAX_CLIENTS:
        raise ValueError(f"ERRAND_CREW_TOKENS allows at most {MAX_CLIENTS} clients")
    for name, secret in tokens.items():
        if not CLIENT_NAME_RE.match(name):
            raise ValueError(
                "client names must be 1-32 chars of lowercase letters, digits, - or _"
            )
        if len(secret) < MIN_TOKEN_LENGTH:
            raise ValueError(
                f"token for client {name!r} must be at least {MIN_TOKEN_LENGTH} characters"
            )
    if len(set(tokens.values())) != len(tokens):
        raise ValueError("each client must have a different token")


def parse_client_tokens(raw: str) -> dict[str, str]:
    """Parse `name:secret,name:secret`. A secret may contain ':' but not ','."""
    tokens: dict[str, str] = {}
    for part in (p.strip() for p in raw.split(",")):
        if not part:
            continue
        name, sep, secret = part.partition(":")
        if not sep:
            raise ValueError("ERRAND_CREW_TOKENS entries must look like name:secret")
        if name in tokens:
            raise ValueError(f"client {name!r} is listed twice")
        tokens[name] = secret
    return tokens


def _int(env: dict[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    if value < 1:
        raise ValueError(f"{name} must be >= 1")
    return value


def _bool(env: dict[str, str], name: str, default: bool) -> bool:
    raw = env.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"{name} must be true or false, got {raw!r}")


def _csv(env: dict[str, str], name: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in env.get(name, "").split(",") if p.strip())


@dataclass(frozen=True)
class Settings:
    # client name -> secret. Each client (demo, judges, dev...) has its own token.
    client_tokens: dict[str, str]
    anthropic_api_key: str = ""
    kernel_api_key: str = ""

    planner_model: str = "claude-sonnet-5-5"
    worker_model: str = "claude-haiku-5-5"
    judge_model: str = "claude-haiku-5-5"

    # Abuse and cost limits (the server is public, and every errand spends credits).
    max_concurrent_errands: int = 2
    max_errands_per_hour: int = 20
    max_errands_per_day: int = 100
    max_sites_per_errand: int = 4

    worker_timeout_s: int = 150  # covers up to 3 pages per site
    max_page_chars: int = 15_000
    kept_errands: int = 100
    # False: Kernel browsers have a screen and a live view you can watch. True: headless.
    kernel_headless: bool = False

    allowed_hosts: tuple[str, ...] = ()
    allowed_origins: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        validate_client_tokens(self.client_tokens)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        e = dict(os.environ if env is None else env)
        hosts = list(_csv(e, "ALLOWED_HOSTS"))
        render_host = e.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
        if render_host and render_host not in hosts:
            hosts.append(render_host)
        return cls(
            client_tokens=parse_client_tokens(e.get("ERRAND_CREW_TOKENS", "")),
            anthropic_api_key=e.get("ANTHROPIC_API_KEY", ""),
            kernel_api_key=e.get("KERNEL_API_KEY", ""),
            planner_model=e.get("PLANNER_MODEL", cls.planner_model),
            worker_model=e.get("WORKER_MODEL", cls.worker_model),
            judge_model=e.get("JUDGE_MODEL", cls.judge_model),
            max_concurrent_errands=_int(e, "MAX_CONCURRENT_ERRANDS", 2),
            max_errands_per_hour=_int(e, "MAX_ERRANDS_PER_HOUR", 20),
            max_errands_per_day=_int(e, "MAX_ERRANDS_PER_DAY", 100),
            allowed_hosts=tuple(hosts),
            kernel_headless=_bool(e, "KERNEL_HEADLESS", False),
            allowed_origins=_csv(e, "ALLOWED_ORIGINS"),
        )
