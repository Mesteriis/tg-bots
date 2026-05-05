from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class BackupRepositoryPrivacyRead(BaseModel):
    service: str | None
    auth_method: str | None
    host: str | None
    owner: str | None
    repo: str | None
    api_url: str | None
    is_private: bool | None
    verified: bool
    message: str


class BackupDiffSectionRead(BaseModel):
    section: str
    before_count: int
    after_count: int
    changed: bool
    row_changes: int


class BackupRowDiffRead(BaseModel):
    section: str
    key: str
    action: Literal["added", "removed", "changed"]
    before: dict[str, Any] | None
    after: dict[str, Any] | None


class BackupDiffRead(BaseModel):
    base_run_id: int | None
    changed_sections: int
    sections: list[BackupDiffSectionRead]
    sections_by_name: dict[str, BackupDiffSectionRead]
    rows: list[BackupRowDiffRead]


class BackupPreflightCheckRead(BaseModel):
    name: str
    status: Literal["ok", "warning", "error", "skipped"]
    message: str


class BackupPreflightRead(BaseModel):
    ok: bool
    include_secrets: bool
    requested_include_secrets: bool
    push_to_git: bool
    repo: BackupRepositoryPrivacyRead
    diff: BackupDiffRead
    checks: list[BackupPreflightCheckRead]


class BackupRunRequest(BaseModel):
    include_secrets: bool | None = None
    push_to_git: bool | None = None


class BackupImportPreviewRequest(BaseModel):
    snapshot: dict[str, Any]
    sections: list[str] | None = None


class BackupImportApplyRequest(BaseModel):
    snapshot: dict[str, Any]
    confirm: str
    sections: list[str] | None = None


class BackupRunRestorePreviewRequest(BaseModel):
    sections: list[str] | None = None


class BackupRunRestoreApplyRequest(BaseModel):
    confirm: str
    sections: list[str] | None = None


class BackupImportPreviewRead(BaseModel):
    ok: bool
    schema_version: str | None
    diff: BackupDiffRead
    blocked_sections: list[str]
    warnings: list[str]
    selected_sections: list[str]
    expanded_sections: list[str]


class BackupImportApplyRead(BaseModel):
    status: str
    restored_rows: int
    restored_sections: int
    safety_backup_run_id: int
    diff: BackupDiffRead
    selected_sections: list[str]
    expanded_sections: list[str]


class BackupRunRead(BaseModel):
    id: int
    status: str
    items_exported: int
    snapshot: dict[str, Any] | None = None
    git_commit: str | None = None
    error_message: str | None = None
    created_at: datetime
    finished_at: datetime | None = None
