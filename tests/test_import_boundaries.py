def test_core_imports_are_available() -> None:
    from tg_bot_aggregator.core.config import Settings
    from tg_bot_aggregator.core.db import create_engine, create_session_factory
    from tg_bot_aggregator.core.errors import NotFoundError
    from tg_bot_aggregator.core.security import REDACTED, redact_secrets
    from tg_bot_aggregator.core.time import utc_now

    assert Settings
    assert create_engine
    assert create_session_factory
    assert issubclass(NotFoundError, ValueError)
    assert redact_secrets({"token": "secret"})["token"] == REDACTED
    assert utc_now().tzinfo is not None


def test_infra_imports_are_available() -> None:
    from tg_bot_aggregator.infra.events import MemoryEventBus
    from tg_bot_aggregator.infra.telegram_client import TelegramBotApiClient

    assert MemoryEventBus
    assert TelegramBotApiClient


def test_domain_repository_imports_are_available() -> None:
    from tg_bot_aggregator.domain.auth.repository import ApiTokenRepository
    from tg_bot_aggregator.domain.backups.repository import BackupRunRepository
    from tg_bot_aggregator.domain.batches.repository import SendBatchRepository
    from tg_bot_aggregator.domain.bots.repository import BotRepository
    from tg_bot_aggregator.domain.destinations.repository import DestinationRepository
    from tg_bot_aggregator.domain.mcp.repository import McpSettingsRepository
    from tg_bot_aggregator.domain.operations.repository import RuntimeSettingsRepository
    from tg_bot_aggregator.domain.sending.repository import SendHistoryRepository
    from tg_bot_aggregator.domain.templates.repository import TemplateRepository

    assert ApiTokenRepository
    assert BackupRunRepository
    assert SendBatchRepository
    assert BotRepository
    assert DestinationRepository
    assert McpSettingsRepository
    assert RuntimeSettingsRepository
    assert SendHistoryRepository
    assert TemplateRepository


def test_domain_service_imports_are_available() -> None:
    from tg_bot_aggregator.domain.analytics.mtproto import MtprotoService
    from tg_bot_aggregator.domain.analytics.service import AnalyticsService
    from tg_bot_aggregator.domain.auth.middleware import ProtectedHostAuthMiddleware
    from tg_bot_aggregator.domain.auth.service import hash_api_token
    from tg_bot_aggregator.domain.backups.service import BackupService
    from tg_bot_aggregator.domain.batches.service import WorkflowService
    from tg_bot_aggregator.domain.mcp.catalog import MCP_TOOL_DEFINITIONS
    from tg_bot_aggregator.domain.mcp.server import create_mcp_server
    from tg_bot_aggregator.domain.media.browser import MediaBrowser
    from tg_bot_aggregator.domain.media.paths import validate_shared_file
    from tg_bot_aggregator.domain.operations.service import OperationsService
    from tg_bot_aggregator.domain.ops.service import TelegramOpsService
    from tg_bot_aggregator.domain.reliability.service import SendRateLimiter
    from tg_bot_aggregator.domain.sending.service import SendService
    from tg_bot_aggregator.domain.templates.renderer import validate_template_text

    assert AnalyticsService
    assert MtprotoService
    assert ProtectedHostAuthMiddleware
    assert hash_api_token
    assert BackupService
    assert WorkflowService
    assert MediaBrowser
    assert validate_shared_file
    assert MCP_TOOL_DEFINITIONS
    assert create_mcp_server
    assert OperationsService
    assert TelegramOpsService
    assert SendRateLimiter
    assert SendService
    assert validate_template_text
