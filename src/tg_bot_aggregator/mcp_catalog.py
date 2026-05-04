from dataclasses import dataclass


@dataclass(frozen=True)
class McpToolDefinition:
    name: str
    title: str
    category: str
    risk: str


MCP_TOOL_DEFINITIONS: tuple[McpToolDefinition, ...] = (
    McpToolDefinition("list_bots", "List bots", "read", "read"),
    McpToolDefinition("list_destinations", "List destinations", "read", "read"),
    McpToolDefinition("list_message_templates", "List templates", "read", "read"),
    McpToolDefinition("get_analytics_summary", "Get analytics summary", "read", "read"),
    McpToolDefinition("get_send_history", "Get send history", "read", "read"),
    McpToolDefinition("list_audit_events", "List audit events", "read", "read"),
    McpToolDefinition("get_discovery_settings", "Get discovery settings", "read", "read"),
    McpToolDefinition("get_mcp_connection_info", "Get MCP connection info", "read", "read"),
    McpToolDefinition("list_media", "List shared media", "read", "read"),
    McpToolDefinition("list_send_profiles", "List send profiles", "read", "read"),
    McpToolDefinition("list_send_batches", "List send batches", "read", "read"),
    McpToolDefinition("list_diagnostic_updates", "List diagnostic updates", "read", "read"),
    McpToolDefinition("get_reliability_summary", "Get reliability summary", "read", "read"),
    McpToolDefinition("get_reliability_graph", "Get reliability graph", "read", "read"),
    McpToolDefinition("list_send_attempts", "List send attempts", "read", "read"),
    McpToolDefinition("list_rate_limit_buckets", "List rate limit buckets", "read", "read"),
    McpToolDefinition("send_text", "Send text", "send", "write"),
    McpToolDefinition("send_template", "Send template", "send", "write"),
    McpToolDefinition("send_file_from_shared_path", "Send shared file", "send", "write"),
    McpToolDefinition("dry_run_send", "Dry run send", "send", "read"),
    McpToolDefinition("create_send_profile", "Create send profile", "send", "write"),
    McpToolDefinition("create_send_batch", "Create send batch", "send", "write"),
    McpToolDefinition("preview_send_batch", "Preview send batch", "send", "read"),
    McpToolDefinition("enqueue_send_batch", "Enqueue send batch", "send", "write"),
    McpToolDefinition("cancel_send_batch", "Cancel send batch", "send", "write"),
    McpToolDefinition(
        "create_destination_from_diagnostic_update",
        "Create destination from diagnostic update",
        "send",
        "write",
    ),
    McpToolDefinition("check_destination", "Check destination", "send", "write"),
    McpToolDefinition("refresh_analytics", "Refresh analytics", "task", "write"),
    McpToolDefinition("release_stale_send_locks", "Release stale send locks", "task", "write"),
    McpToolDefinition("bulk_retry_sends", "Bulk retry sends", "send", "write"),
    McpToolDefinition("bulk_cancel_sends", "Bulk cancel sends", "send", "write"),
    McpToolDefinition("inspect_bot_access", "Inspect bot access", "ops", "read"),
    McpToolDefinition("list_ops_facts", "List Telegram Ops facts", "ops", "read"),
    McpToolDefinition("run_ops_scan", "Run Telegram Ops scan", "ops", "write"),
    McpToolDefinition(
        "list_ops_recommendations",
        "List Telegram Ops recommendations",
        "ops",
        "read",
    ),
    McpToolDefinition("preview_ops_action", "Preview Telegram Ops action", "ops", "write"),
    McpToolDefinition("apply_ops_action", "Apply Telegram Ops action", "ops", "admin"),
    McpToolDefinition(
        "dismiss_ops_recommendation",
        "Dismiss Telegram Ops recommendation",
        "ops",
        "write",
    ),
    McpToolDefinition("list_ops_rules", "List Telegram Ops rules", "ops", "read"),
    McpToolDefinition("update_ops_rule", "Update Telegram Ops rule", "ops", "admin"),
    McpToolDefinition("run_ops_rule", "Run Telegram Ops rule", "ops", "admin"),
    McpToolDefinition("pause_ops_rule", "Pause Telegram Ops rule", "ops", "admin"),
    McpToolDefinition("resume_ops_rule", "Resume Telegram Ops rule", "ops", "admin"),
    McpToolDefinition("explain_failed_send", "Explain failed send", "ops", "read"),
    McpToolDefinition("get_mcp_coverage_matrix", "Get MCP coverage matrix", "ops", "read"),
    McpToolDefinition("recommend_mcp_preset", "Recommend MCP preset", "ops", "read"),
    McpToolDefinition("update_discovery_settings", "Update discovery settings", "task", "write"),
    McpToolDefinition("list_api_tokens", "List API tokens", "security", "admin"),
    McpToolDefinition("create_api_token", "Create API token", "security", "admin"),
    McpToolDefinition("revoke_api_token", "Revoke API token", "security", "admin"),
)

MCP_TOOL_NAMES: tuple[str, ...] = tuple(tool.name for tool in MCP_TOOL_DEFINITIONS)
MCP_READ_ONLY_TOOL_NAMES: tuple[str, ...] = tuple(
    tool.name for tool in MCP_TOOL_DEFINITIONS if tool.risk == "read"
)
MCP_BOOTSTRAP_ENABLED_TOOL_NAMES: tuple[str, ...] = MCP_READ_ONLY_TOOL_NAMES
MCP_SENDER_TOOL_NAMES: tuple[str, ...] = tuple(
    tool.name for tool in MCP_TOOL_DEFINITIONS if tool.category in {"read", "send"}
)

MCP_DEFAULT_ENABLED_TOOL_NAMES: tuple[str, ...] = (
    "list_bots",
    "list_destinations",
    "list_message_templates",
    "get_analytics_summary",
    "get_send_history",
    "list_audit_events",
    "get_discovery_settings",
    "send_text",
    "send_template",
    "send_file_from_shared_path",
    "dry_run_send",
    "check_destination",
    "refresh_analytics",
    "update_discovery_settings",
    "list_api_tokens",
    "create_api_token",
    "revoke_api_token",
    "get_reliability_summary",
    "get_reliability_graph",
    "list_send_attempts",
    "list_rate_limit_buckets",
    "release_stale_send_locks",
    "bulk_retry_sends",
    "bulk_cancel_sends",
    "list_ops_facts",
    "list_ops_recommendations",
    "list_ops_rules",
    "explain_failed_send",
    "get_mcp_coverage_matrix",
    "recommend_mcp_preset",
)
