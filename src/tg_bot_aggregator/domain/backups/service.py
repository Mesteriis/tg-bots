import json
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse, urlunparse

import httpx
from anyio import to_thread
from sqlalchemy import DateTime, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.core.security import redact_secrets, redact_text
from tg_bot_aggregator.models import (
    ApiToken,
    Bot,
    BotDiscoverySettings,
    Destination,
    DiagnosticBotSettings,
    McpSettings,
    MessageTemplate,
    MessageTemplateVersion,
    RuntimeAdvancedSettings,
    RuntimeSettings,
    SendProfile,
)
from tg_bot_aggregator.schemas import RuntimeSettingsRead

BACKUP_MODELS: tuple[tuple[str, type[Any]], ...] = (
    ("bots", Bot),
    ("destinations", Destination),
    ("templates", MessageTemplate),
    ("template_versions", MessageTemplateVersion),
    ("send_profiles", SendProfile),
    ("mcp_settings", McpSettings),
    ("discovery_settings", BotDiscoverySettings),
    ("diagnostic_settings", DiagnosticBotSettings),
    ("api_tokens", ApiToken),
    ("runtime_settings", RuntimeSettings),
    ("runtime_advanced_settings", RuntimeAdvancedSettings),
)
BACKUP_SECTION_KEYS = tuple(key for key, _ in BACKUP_MODELS)
RESTORE_SECTION_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "templates": ("template_versions",),
}

SECRET_FIELDS = {
    "backup_git_repo_url",
    "backup_git_api_token",
    "callback_url",
    "database_url",
    "redis_url",
    "telegram_api_hash",
    "token",
    "token_hash",
}


class BackupServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitRepositoryRef:
    host: str
    owner: str
    repo: str


@dataclass(frozen=True)
class RepositoryPrivacy:
    service: str | None
    auth_method: str | None
    host: str | None
    owner: str | None
    repo: str | None
    api_url: str | None
    is_private: bool | None
    verified: bool
    message: str


_SCP_GIT_URL_RE = re.compile(r"^(?:[^@]+@)?(?P<host>[^:]+):(?P<path>.+)$")


def _json_value(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _row_to_dict(row: Any, include_secrets: bool) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for column in row.__table__.columns:
        if not include_secrets and column.name in SECRET_FIELDS:
            continue
        value = getattr(row, column.name)
        if not include_secrets and column.name == "settings_json" and isinstance(value, dict):
            value = {key: item for key, item in value.items() if key not in SECRET_FIELDS}
        data[column.name] = _json_value(value)
    return data


def _run_git(args: list[str], cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            check=False,
            text=True,
            capture_output=True,
        )
    except FileNotFoundError as exc:
        raise BackupServiceError(
            "git executable is not installed in the application container"
        ) from exc
    if result.returncode != 0:
        raise BackupServiceError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def _strip_git_suffix(repo: str) -> str:
    return repo[:-4] if repo.endswith(".git") else repo


def _parse_git_repo_url(repo_url: str | None) -> GitRepositoryRef | None:
    if not repo_url:
        return None
    value = repo_url.strip()
    if not value:
        return None

    if "://" not in value:
        match = _SCP_GIT_URL_RE.match(value)
        if not match:
            return None
        host = match.group("host").lower()
        path = match.group("path").strip("/")
    else:
        parsed = urlparse(value)
        if not parsed.hostname:
            return None
        host = parsed.hostname.lower()
        path = parsed.path.strip("/")

    parts = [part for part in path.split("/") if part]
    if len(parts) < 2:
        return None
    return GitRepositoryRef(host=host, owner=parts[-2], repo=_strip_git_suffix(parts[-1]))


def _resolve_git_service(configured: str | None, host: str) -> str:
    value = (configured or "auto").strip().lower()
    if value in {"github", "gitea"}:
        return value
    return "github" if host == "github.com" else "gitea"


def _join_api_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _repo_api_url(settings: RuntimeSettingsRead, ref: GitRepositoryRef, service: str) -> str:
    owner = quote(ref.owner, safe="")
    repo = quote(ref.repo, safe="")
    if service == "github":
        base_url = settings.backup_git_api_base_url or "https://api.github.com"
    else:
        base_url = settings.backup_git_api_base_url or f"https://{ref.host}/api/v1"
    return _join_api_url(base_url, f"repos/{owner}/{repo}")


def _repo_api_headers(settings: RuntimeSettingsRead, service: str) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if service == "github":
        headers["Accept"] = "application/vnd.github+json"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    token = settings.backup_git_api_token
    if token and settings.backup_git_auth_method == "token":
        headers["Authorization"] = f"Bearer {token}" if service == "github" else f"token {token}"
    return headers


def _authenticated_git_repo_url(
    settings: RuntimeSettingsRead,
    repo_url: str,
    service: str,
) -> str:
    token = settings.backup_git_api_token
    if not token or settings.backup_git_auth_method != "token":
        return repo_url

    parsed = urlparse(repo_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        return repo_url

    username = "x-access-token" if service == "github" else "oauth2"
    password = quote(token, safe="")
    host = parsed.hostname
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunparse(parsed._replace(netloc=f"{username}:{password}@{host}"))


def normalize_restore_sections(
    sections: list[str] | tuple[str, ...] | None,
) -> tuple[list[str], list[str]]:
    if sections is None:
        all_sections = list(BACKUP_SECTION_KEYS)
        return all_sections, all_sections

    selected: list[str] = []
    invalid: list[str] = []
    for section in sections:
        if section not in BACKUP_SECTION_KEYS:
            invalid.append(section)
            continue
        if section not in selected:
            selected.append(section)
    if invalid:
        raise BackupServiceError(f"unknown backup sections: {', '.join(sorted(set(invalid)))}")
    if not selected:
        raise BackupServiceError("at least one backup section must be selected")

    expanded = set(selected)
    for section in selected:
        expanded.update(RESTORE_SECTION_DEPENDENCIES.get(section, ()))
    return selected, [section for section in BACKUP_SECTION_KEYS if section in expanded]


def _snapshot_section_items(snapshot: dict[str, Any] | None, section: str) -> list[dict[str, Any]]:
    if snapshot is None:
        return []
    items = snapshot.get(section, [])
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _row_identity(row: dict[str, Any]) -> str:
    for field in ("id", "tag", "alias", "name", "token_prefix", "chat_id"):
        value = row.get(field)
        if value not in (None, ""):
            return f"{field}:{value}"
    return json.dumps(row, ensure_ascii=False, sort_keys=True)


def _section_row_diff(
    section: str,
    before_items: list[dict[str, Any]],
    after_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    before = {_row_identity(row): row for row in before_items}
    after = {_row_identity(row): row for row in after_items}
    rows: list[dict[str, Any]] = []
    for key in sorted(before.keys() | after.keys()):
        before_row = before.get(key)
        after_row = after.get(key)
        if before_row == after_row:
            continue
        action = "changed"
        if before_row is None:
            action = "added"
        elif after_row is None:
            action = "removed"
        rows.append(
            {
                "section": section,
                "key": key,
                "action": action,
                "before": redact_secrets(before_row) if before_row is not None else None,
                "after": redact_secrets(after_row) if after_row is not None else None,
            }
        )
    return rows


def _row_int_value(row: dict[str, Any], field: str) -> int | None:
    value = row.get(field)
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def summarize_snapshot_diff(
    current: dict[str, Any],
    previous: dict[str, Any] | None,
    base_run_id: int | None = None,
    sections_filter: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    sections: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    sections_to_compare = sections_filter or BACKUP_SECTION_KEYS
    for section in sections_to_compare:
        before_items = _snapshot_section_items(previous, section)
        after_items = _snapshot_section_items(current, section)
        row_diff = _section_row_diff(section, before_items, after_items)
        rows.extend(row_diff)
        sections.append(
            {
                "section": section,
                "before_count": len(before_items),
                "after_count": len(after_items),
                "changed": before_items != after_items,
                "row_changes": len(row_diff),
            }
        )
    sections_by_name = {section["section"]: section for section in sections}
    return {
        "base_run_id": base_run_id,
        "changed_sections": sum(1 for section in sections if section["changed"]),
        "sections": sections,
        "sections_by_name": sections_by_name,
        "rows": rows,
    }


def _required_import_fields(model: type[Any]) -> set[str]:
    fields: set[str] = set()
    for column in model.__table__.columns:
        if (
            not column.nullable
            and not column.primary_key
            and column.default is None
            and column.server_default is None
        ):
            fields.add(column.name)
    return fields


def _coerce_import_value(column: Any, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(column.type, DateTime) and isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


def _import_row_values(model: type[Any], row: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    columns = {column.name: column for column in model.__table__.columns}
    for key, value in row.items():
        column = columns.get(key)
        if column is not None:
            values[key] = _coerce_import_value(column, value)
    return values


class BackupService:
    def __init__(
        self,
        session: AsyncSession,
        settings: RuntimeSettingsRead,
        workdir: Path | str = "data/backup-repo",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.workdir = Path(workdir)
        self.http_client = http_client

    async def inspect_repository_privacy(self) -> RepositoryPrivacy:
        ref = _parse_git_repo_url(self.settings.backup_git_repo_url)
        if ref is None:
            return RepositoryPrivacy(
                service=None,
                auth_method=None,
                host=None,
                owner=None,
                repo=None,
                api_url=None,
                is_private=None,
                verified=False,
                message="git repository is not configured or cannot be parsed",
            )

        service = _resolve_git_service(self.settings.backup_git_service, ref.host)
        auth_method = self.settings.backup_git_auth_method
        api_url = _repo_api_url(self.settings, ref, service)
        headers = _repo_api_headers(self.settings, service)
        try:
            response = await self._get_repo(api_url, headers)
        except httpx.RequestError as exc:
            return RepositoryPrivacy(
                service=service,
                auth_method=auth_method,
                host=ref.host,
                owner=ref.owner,
                repo=ref.repo,
                api_url=api_url,
                is_private=None,
                verified=False,
                message=f"repo privacy check failed: {redact_text(str(exc))}",
            )

        if response.status_code in {401, 403, 404}:
            return RepositoryPrivacy(
                service=service,
                auth_method=auth_method,
                host=ref.host,
                owner=ref.owner,
                repo=ref.repo,
                api_url=api_url,
                is_private=None,
                verified=False,
                message=(
                    "repo privacy is unknown; API token may be missing, invalid, "
                    "or not allowed to read this repository"
                ),
            )
        if response.status_code >= 400:
            return RepositoryPrivacy(
                service=service,
                auth_method=auth_method,
                host=ref.host,
                owner=ref.owner,
                repo=ref.repo,
                api_url=api_url,
                is_private=None,
                verified=False,
                message=f"repo privacy check returned HTTP {response.status_code}",
            )

        try:
            data = response.json()
        except ValueError:
            return RepositoryPrivacy(
                service=service,
                auth_method=auth_method,
                host=ref.host,
                owner=ref.owner,
                repo=ref.repo,
                api_url=api_url,
                is_private=None,
                verified=False,
                message="repo privacy check returned non-JSON response",
            )

        is_private = data.get("private")
        if not isinstance(is_private, bool):
            return RepositoryPrivacy(
                service=service,
                auth_method=auth_method,
                host=ref.host,
                owner=ref.owner,
                repo=ref.repo,
                api_url=api_url,
                is_private=None,
                verified=False,
                message="repo privacy check response does not include boolean private field",
            )
        return RepositoryPrivacy(
            service=service,
            auth_method=auth_method,
            host=ref.host,
            owner=ref.owner,
            repo=ref.repo,
            api_url=api_url,
            is_private=is_private,
            verified=True,
            message="repo privacy verified",
        )

    async def _get_repo(self, api_url: str, headers: dict[str, str]) -> httpx.Response:
        if self.http_client is not None:
            return await self.http_client.get(api_url, headers=headers)
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            return await client.get(api_url, headers=headers)

    async def export_snapshot(
        self,
        include_secrets: bool,
        repo_privacy: RepositoryPrivacy | None = None,
        requested_include_secrets: bool = False,
    ) -> tuple[dict[str, Any], int]:
        reason = "manual_setting" if requested_include_secrets else "excluded"
        if repo_privacy is not None and repo_privacy.is_private is True:
            reason = "private_repo"
        snapshot: dict[str, Any] = {
            "schema_version": "v1",
            "backup_policy": {
                "include_secrets": include_secrets,
                "requested_include_secrets": requested_include_secrets,
                "secret_reason": reason,
                "repo": asdict(repo_privacy) if repo_privacy is not None else None,
            },
        }
        count = 0
        for key, model in BACKUP_MODELS:
            result = await self.session.execute(select(model).order_by(model.id))
            rows = list(result.scalars().all())
            snapshot[key] = [_row_to_dict(row, include_secrets) for row in rows]
            count += len(rows)
        return snapshot, count

    async def preview_import_snapshot(
        self,
        snapshot: dict[str, Any],
        sections: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        self._validate_import_snapshot(snapshot)
        selected_sections, expanded_sections = normalize_restore_sections(sections)
        current, _ = await self.export_snapshot(include_secrets=True)
        diff = summarize_snapshot_diff(snapshot, current, sections_filter=expanded_sections)
        field_blocked_sections = self._blocked_import_sections(snapshot, expanded_sections)
        reference_blocked, reference_warnings = await self._reference_blockers(
            snapshot,
            expanded_sections,
        )
        blocked_sections = sorted({*field_blocked_sections, *reference_blocked})
        return {
            "ok": not blocked_sections,
            "schema_version": snapshot.get("schema_version"),
            "diff": diff,
            "blocked_sections": blocked_sections,
            "warnings": self._import_warnings(snapshot, field_blocked_sections)
            + reference_warnings,
            "selected_sections": selected_sections,
            "expanded_sections": expanded_sections,
        }

    async def apply_import_snapshot(
        self,
        snapshot: dict[str, Any],
        sections: list[str] | tuple[str, ...] | None = None,
    ) -> int:
        preview = await self.preview_import_snapshot(snapshot, sections)
        if not preview["ok"]:
            warnings = "; ".join(preview["warnings"])
            blocked = ", ".join(preview["blocked_sections"])
            detail = warnings or f"blocked backup sections: {blocked}"
            raise BackupServiceError(f"restore blocked: {detail}")

        restored = 0
        expanded_sections = set(preview["expanded_sections"])
        selected_models = [
            (section, model) for section, model in BACKUP_MODELS if section in expanded_sections
        ]
        for _, model in reversed(selected_models):
            await self.session.execute(delete(model))
        for section, model in selected_models:
            rows = snapshot.get(section, [])
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                self.session.add(model(**_import_row_values(model, row)))
                restored += 1
        await self.session.flush()
        return restored

    def _validate_import_snapshot(self, snapshot: dict[str, Any]) -> None:
        if snapshot.get("schema_version") != "v1":
            raise BackupServiceError("unsupported backup schema_version")
        for section in BACKUP_SECTION_KEYS:
            rows = snapshot.get(section, [])
            if not isinstance(rows, list):
                raise BackupServiceError(f"backup section {section} must be a list")
            if any(not isinstance(row, dict) for row in rows):
                raise BackupServiceError(f"backup section {section} contains non-object rows")

    def _blocked_import_sections(
        self,
        snapshot: dict[str, Any],
        sections: list[str] | tuple[str, ...] | None = None,
    ) -> list[str]:
        blocked: list[str] = []
        sections_to_check = set(sections or BACKUP_SECTION_KEYS)
        for section, model in BACKUP_MODELS:
            if section not in sections_to_check:
                continue
            required = _required_import_fields(model)
            if not required:
                continue
            rows = snapshot.get(section, [])
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if any(row.get(field) is None for field in required):
                    blocked.append(section)
                    break
        return blocked

    def _import_warnings(self, snapshot: dict[str, Any], blocked_sections: list[str]) -> list[str]:
        warnings: list[str] = []
        if blocked_sections:
            warnings.append(
                "snapshot is missing required fields; it was likely created with secrets excluded"
            )
        if snapshot.get("backup_policy", {}).get("include_secrets") is False:
            warnings.append("snapshot metadata says secrets were excluded")
        return warnings

    async def _reference_blockers(
        self,
        snapshot: dict[str, Any],
        sections: list[str] | tuple[str, ...],
    ) -> tuple[list[str], list[str]]:
        if "destinations" not in sections:
            return [], []

        referenced_bot_ids = {
            value
            for row in _snapshot_section_items(snapshot, "destinations")
            if (value := _row_int_value(row, "bot_id")) is not None
        }
        if not referenced_bot_ids:
            return [], []

        if "bots" in sections:
            available_bot_ids = {
                value
                for row in _snapshot_section_items(snapshot, "bots")
                if (value := _row_int_value(row, "id")) is not None
            }
        else:
            result = await self.session.execute(select(Bot.id))
            available_bot_ids = {int(value) for value in result.scalars().all()}

        missing = sorted(referenced_bot_ids - available_bot_ids)
        if not missing:
            return [], []
        ids = ", ".join(str(item) for item in missing)
        return ["destinations"], [
            (
                f"destinations reference missing bot IDs: {ids}; "
                "restore bots too or create matching bots before restoring destinations"
            )
        ]

    async def push_snapshot(self, snapshot: dict[str, Any]) -> str | None:
        if not self.settings.backup_git_repo_url:
            return None
        return await to_thread.run_sync(self._push_snapshot_sync, snapshot)

    def _push_snapshot_sync(self, snapshot: dict[str, Any]) -> str | None:
        repo_url = self.settings.backup_git_repo_url
        if not repo_url:
            return None
        branch = self.settings.backup_git_branch or "main"
        ref = _parse_git_repo_url(repo_url)
        service = (
            _resolve_git_service(self.settings.backup_git_service, ref.host)
            if ref
            else "gitea"
        )
        auth_repo_url = _authenticated_git_repo_url(self.settings, repo_url, service)
        if not (self.workdir / ".git").exists():
            self.workdir.parent.mkdir(parents=True, exist_ok=True)
            _run_git(["git", "clone", "--branch", branch, auth_repo_url, str(self.workdir)])
            _run_git(["git", "remote", "set-url", "origin", repo_url], cwd=self.workdir)

        try:
            _run_git(["git", "remote", "set-url", "origin", auth_repo_url], cwd=self.workdir)
            _run_git(["git", "fetch", "origin"], cwd=self.workdir)
            _run_git(["git", "checkout", branch], cwd=self.workdir)
            _run_git(["git", "pull", "--ff-only"], cwd=self.workdir)

            backup_path = self.workdir / (self.settings.backup_git_path or "tg-bots.json")
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            backup_path.write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            _run_git(["git", "add", str(backup_path.relative_to(self.workdir))], cwd=self.workdir)
            diff_status = _run_git(["git", "status", "--porcelain"], cwd=self.workdir)
            if not diff_status:
                return None
            _run_git(["git", "commit", "-m", "backup: update tg-bots snapshot"], cwd=self.workdir)
            commit = _run_git(["git", "rev-parse", "HEAD"], cwd=self.workdir)
            _run_git(["git", "push", "origin", branch], cwd=self.workdir)
            return commit
        finally:
            if (self.workdir / ".git").exists():
                _run_git(["git", "remote", "set-url", "origin", repo_url], cwd=self.workdir)
