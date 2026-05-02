from tg_bot_aggregator.config import Settings
from tg_bot_aggregator.tasks import create_broker


def test_taskiq_broker_can_be_constructed() -> None:
    broker = create_broker(Settings(REDIS_URL="redis://localhost:6379/15"))

    assert broker is not None
    assert hasattr(broker, "task")

