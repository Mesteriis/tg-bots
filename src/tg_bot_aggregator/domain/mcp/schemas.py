from pydantic import BaseModel


class McpToolRead(BaseModel):
    name: str
    title: str
    category: str
    risk: str
    enabled: bool


class McpSettingsRead(BaseModel):
    is_enabled: bool
    allow_legacy_sse: bool
    protected_hosts: list[str]
    transports: list[dict[str, str | bool]]
    tools: list[McpToolRead]
    tools_by_name: dict[str, McpToolRead]


class McpTransportInfo(BaseModel):
    name: str
    path: str
    enabled: bool


class McpConnectionInfoRead(BaseModel):
    streamable_http: McpTransportInfo
    legacy_sse: McpTransportInfo
    legacy_messages: McpTransportInfo
    protected_hosts: list[str]
    required_headers: list[str]
    enabled_tools: list[str]
    local_examples: dict[str, str]
    protected_host_examples: dict[str, str]


class McpCoverageRead(BaseModel):
    rows: list[dict[str, object]]
    missing_enabled_tools: list[str]
    missing_catalog_tools: list[str]


class McpSettingsUpdate(BaseModel):
    is_enabled: bool | None = None
    allow_legacy_sse: bool | None = None
    enabled_tools: list[str] | None = None
