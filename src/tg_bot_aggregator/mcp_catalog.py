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
    McpToolDefinition("send_text", "Send text", "send", "write"),
    McpToolDefinition("send_template", "Send template", "send", "write"),
    McpToolDefinition("send_file_from_shared_path", "Send shared file", "send", "write"),
    McpToolDefinition("refresh_analytics", "Refresh analytics", "task", "write"),
    McpToolDefinition("list_api_tokens", "List API tokens", "security", "admin"),
    McpToolDefinition("create_api_token", "Create API token", "security", "admin"),
    McpToolDefinition("revoke_api_token", "Revoke API token", "security", "admin"),
)

MCP_TOOL_NAMES: tuple[str, ...] = tuple(tool.name for tool in MCP_TOOL_DEFINITIONS)
MCP_READ_ONLY_TOOL_NAMES: tuple[str, ...] = tuple(
    tool.name for tool in MCP_TOOL_DEFINITIONS if tool.risk == "read"
)
MCP_SENDER_TOOL_NAMES: tuple[str, ...] = tuple(
    tool.name for tool in MCP_TOOL_DEFINITIONS if tool.category in {"read", "send"}
)
