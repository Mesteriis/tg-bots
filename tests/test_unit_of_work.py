import pytest

from tg_bot_aggregator.infra.uow import UnitOfWork


class FakeSession:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False
        self.closed = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_unit_of_work_commits_and_closes_on_success() -> None:
    session = FakeSession()

    async with UnitOfWork(lambda: session) as uow:
        assert uow.session is session
        assert uow.bots
        assert uow.tokens
        assert uow.destinations
        assert uow.templates
        assert uow.sending
        assert uow.attempts
        assert uow.batches
        assert uow.backups
        assert uow.ops
        assert uow.audit

    assert session.committed is True
    assert session.rolled_back is False
    assert session.closed is True


@pytest.mark.asyncio
async def test_unit_of_work_rolls_back_and_closes_on_error() -> None:
    session = FakeSession()

    with pytest.raises(RuntimeError):
        async with UnitOfWork(lambda: session):
            raise RuntimeError("boom")

    assert session.committed is False
    assert session.rolled_back is True
    assert session.closed is True
