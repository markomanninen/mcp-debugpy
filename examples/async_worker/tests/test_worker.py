import asyncio

import pytest

from ..worker import Job, gather_results


@pytest.mark.asyncio
async def test_gather_results_returns_values():
    jobs = [Job("one", 0.0, 1), Job("two", 0.0, 2)]
    with pytest.raises((TypeError, RuntimeError)):
        # BUG: gather_results returns unfinished awaitables
        await gather_results(jobs)


@pytest.mark.asyncio
@pytest.mark.xfail(reason="await missing in gather_results", strict=True)
async def test_gather_results_success():
    jobs = [Job("one", 0.0, 1), Job("two", 0.0, 2)]
    assert await gather_results(jobs) == [1, 2]
