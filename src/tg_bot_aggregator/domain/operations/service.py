from typing import Any

from tg_bot_aggregator.core.errors import NotFoundError
from tg_bot_aggregator.domain.batches.service import WorkflowService
from tg_bot_aggregator.domain.sending.service import SendService, SendServiceError
from tg_bot_aggregator.domain.templates.renderer import TemplateRenderError
from tg_bot_aggregator.schemas import SendPreflightCheckRead, SendPreflightRead, SendPreviewRead


class OperationsService:
    def __init__(self, send_service: SendService) -> None:
        self.send_service = send_service
        self.workflow = WorkflowService(send_service)

    async def preflight_send(self, kind: str, **values: Any) -> SendPreflightRead:
        checks: list[SendPreflightCheckRead] = []
        bot_id = values.get("bot_id")
        try:
            await self.send_service._bot_token(bot_id)
            checks.append(
                SendPreflightCheckRead(name="bot", status="ok", message="bot is active")
            )
        except Exception as exc:
            checks.append(
                SendPreflightCheckRead(name="bot", status="error", message=str(exc))
            )

        policy_errors = await self.send_service.check_send_policy(bot_id)
        for message in policy_errors:
            checks.append(SendPreflightCheckRead(name="policy", status="error", message=message))
        if not policy_errors:
            checks.append(
                SendPreflightCheckRead(name="policy", status="ok", message="policy passed")
            )

        preview: SendPreviewRead | None = None
        try:
            preview_data = await self.workflow.preview_send(kind=kind, **values)
            preview = SendPreviewRead(**preview_data)
            checks.append(
                SendPreflightCheckRead(
                    name="target",
                    status="ok",
                    message="target resolved",
                    data={"chat_id": preview.chat_id},
                )
            )
            checks.append(
                SendPreflightCheckRead(
                    name="payload",
                    status="ok",
                    message=f"{preview.method} payload is valid",
                )
            )
        except (NotFoundError, SendServiceError, TemplateRenderError) as exc:
            checks.append(
                SendPreflightCheckRead(name="payload", status="error", message=str(exc))
            )

        return SendPreflightRead(
            ok=not any(check.status == "error" for check in checks),
            checks=checks,
            preview=preview,
        )
