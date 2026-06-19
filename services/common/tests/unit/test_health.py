"""Unit tests for health/readiness + Prometheus helpers."""
from prometheus_client import CollectorRegistry, Counter

from common.health import (
    check_database,
    check_redis,
    liveness,
    metrics_payload,
    readiness,
)


def test_liveness_has_no_deps() -> None:
    assert liveness() == {"status": "ok"}


async def test_readiness_all_ok() -> None:
    async def ok() -> bool:
        return True

    ready, detail = await readiness({"db": ok, "redis": ok})
    assert ready is True
    assert detail == {"db": "ok", "redis": "ok"}


async def test_readiness_one_failure() -> None:
    async def ok() -> bool:
        return True

    async def bad() -> bool:
        return False

    ready, detail = await readiness({"db": ok, "redis": bad})
    assert ready is False
    assert detail == {"db": "ok", "redis": "fail"}


async def test_readiness_exception_is_failure() -> None:
    async def boom() -> bool:
        raise RuntimeError("down")

    ready, detail = await readiness({"db": boom})
    assert ready is False
    assert detail == {"db": "fail"}


class _FakeDB:
    def __init__(self, value: object, *, raises: bool = False) -> None:
        self._value = value
        self._raises = raises

    async def fetchval(self, query: str, *args: object) -> object:
        if self._raises:
            raise RuntimeError("connection refused")
        return self._value


async def test_check_database_true_on_select_1() -> None:
    assert await check_database(_FakeDB(1)) is True  # type: ignore[arg-type]


async def test_check_database_false_on_bad_value() -> None:
    assert await check_database(_FakeDB(0)) is False  # type: ignore[arg-type]


async def test_check_database_false_on_error() -> None:
    assert await check_database(_FakeDB(None, raises=True)) is False  # type: ignore[arg-type]


class _FakeRedis:
    def __init__(self, *, ping_result: bool = True, raises: bool = False) -> None:
        self._ping_result = ping_result
        self._raises = raises

    async def ping(self) -> bool:
        if self._raises:
            raise ConnectionError("redis down")
        return self._ping_result


async def test_check_redis_true_on_ping() -> None:
    assert await check_redis(_FakeRedis(ping_result=True)) is True


async def test_check_redis_false_on_exception() -> None:
    assert await check_redis(_FakeRedis(raises=True)) is False


def test_metrics_payload_returns_bytes_and_content_type() -> None:
    registry = CollectorRegistry()
    Counter("test_total", "A test counter", registry=registry).inc()
    body, content_type = metrics_payload(registry)
    assert isinstance(body, bytes)
    assert b"test_total" in body
    assert "text/plain" in content_type
