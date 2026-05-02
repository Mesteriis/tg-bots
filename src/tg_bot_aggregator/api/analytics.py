from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.api.dependencies import get_session
from tg_bot_aggregator.repositories import AnalyticsRepository
from tg_bot_aggregator.schemas import (
    AnalyticsRefreshRequest,
    AnalyticsRefreshResponse,
    AnalyticsRunRead,
    AnalyticsSnapshotRead,
    AnalyticsTargetCreate,
    AnalyticsTargetRead,
    AnalyticsTargetUpdate,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/targets", response_model=list[AnalyticsTargetRead])
async def list_targets(session: AsyncSession = Depends(get_session)) -> list[object]:
    return await AnalyticsRepository(session).list_targets()


@router.post("/targets", response_model=AnalyticsTargetRead, status_code=201)
async def create_target(
    payload: AnalyticsTargetCreate,
    session: AsyncSession = Depends(get_session),
) -> object:
    row = await AnalyticsRepository(session).create_target(**payload.model_dump())
    await session.commit()
    return row


@router.get("/targets/{target_id}", response_model=AnalyticsTargetRead)
async def get_target(target_id: int, session: AsyncSession = Depends(get_session)) -> object:
    row = await AnalyticsRepository(session).get_target(target_id)
    if row is None:
        raise HTTPException(status_code=404, detail="analytics target not found")
    return row


@router.patch("/targets/{target_id}", response_model=AnalyticsTargetRead)
async def update_target(
    target_id: int,
    payload: AnalyticsTargetUpdate,
    session: AsyncSession = Depends(get_session),
) -> object:
    repo = AnalyticsRepository(session)
    if await repo.get_target(target_id) is None:
        raise HTTPException(status_code=404, detail="analytics target not found")
    row = await repo.update_target(target_id, **payload.model_dump(exclude_unset=True))
    await session.commit()
    return row


@router.delete("/targets/{target_id}", status_code=204)
async def delete_target(target_id: int, session: AsyncSession = Depends(get_session)) -> None:
    deleted = await AnalyticsRepository(session).delete_target(target_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="analytics target not found")
    await session.commit()


@router.post("/refresh", response_model=AnalyticsRefreshResponse)
async def refresh(
    payload: AnalyticsRefreshRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> AnalyticsRefreshResponse:
    repo = AnalyticsRepository(session)
    target_id = payload.target_id
    if target_id is None:
        raise HTTPException(status_code=400, detail="target_id is required in version 1")
    if await repo.get_target(target_id) is None:
        raise HTTPException(status_code=404, detail="analytics target not found")
    run = await repo.create_run(target_id=target_id, status="queued")
    await session.commit()
    await request.app.state.event_bus.publish(
        "analytics.run.queued", {"run_id": run.id, "target_id": target_id}
    )
    task_id = None
    enqueue = getattr(request.app.state, "enqueue_analytics_refresh", None)
    if enqueue is not None:
        task_id = await enqueue(target_id, run.id)
        run.task_id = task_id
        await session.commit()
    return AnalyticsRefreshResponse(run_id=run.id, status=run.status, task_id=task_id)


@router.get("/runs", response_model=list[AnalyticsRunRead])
async def list_runs(session: AsyncSession = Depends(get_session)) -> list[object]:
    return await AnalyticsRepository(session).list_runs()


@router.get("/snapshots", response_model=list[AnalyticsSnapshotRead])
async def list_snapshots(
    target_id: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[object]:
    return await AnalyticsRepository(session).list_snapshots(target_id=target_id)
