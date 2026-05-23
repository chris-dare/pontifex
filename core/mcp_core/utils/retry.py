import asyncio
import random
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import TypeVar

T = TypeVar("T")


def async_retry(
    attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 4.0,
    jitter: float = 0.2,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Retry an async callable with exponential backoff and jitter."""

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args: object, **kwargs: object) -> T:
            delay = base_delay
            last_exc: BaseException | None = None
            for attempt in range(1, attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt == attempts:
                        break
                    sleep_for = min(delay, max_delay) + random.uniform(-jitter, jitter)
                    sleep_for = max(0.0, sleep_for)
                    await asyncio.sleep(sleep_for)
                    delay *= 2
            assert last_exc is not None
            raise last_exc

        return wrapper

    return decorator
