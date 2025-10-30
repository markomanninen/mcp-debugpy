"""
Async worker demo with an intentional bug in result aggregation.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Iterable, List


@dataclass
class Job:
    name: str
    delay: float
    value: int


async def _run_job(job: Job) -> int:
    await asyncio.sleep(job.delay)
    return job.value


async def gather_results(jobs: Iterable[Job]) -> List[int]:
    tasks = [_run_job(job) for job in jobs]
    # BUG: missing await on asyncio.gather
    results = asyncio.gather(*tasks)
    return list(results)


async def main() -> None:
    jobs = [
        Job(name="alpha", delay=0.1, value=3),
        Job(name="beta", delay=0.2, value=4),
    ]
    values = await gather_results(jobs)
    print(f"Processed values: {values}")


if __name__ == "__main__":
    asyncio.run(main())
