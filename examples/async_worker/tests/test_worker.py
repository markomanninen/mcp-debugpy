import pytest

from ..worker import Job, gather_results


@pytest.mark.asyncio
async def test_gather_results_returns_values():
    jobs = [Job("one", 0.0, 1), Job("two", 0.0, 2)]
    # gather_results should return the processed values
    assert await gather_results(jobs) == [1, 2]


@pytest.mark.asyncio
async def test_gather_results_success():
    jobs = [Job("one", 0.0, 1), Job("two", 0.0, 2)]
    assert await gather_results(jobs) == [1, 2]
