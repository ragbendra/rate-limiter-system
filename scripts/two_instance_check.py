"""Send one identifier's requests through two rate-limiter instances."""

import argparse
import asyncio
import time

import httpx


async def run(base_url_a: str, base_url_b: str, identifier: str) -> None:
    urls = [base_url_a, base_url_b]
    requests = [
        (urls[index % 2].rstrip("/") + "/check", index)
        for index in range(300)
    ]
    limits = httpx.Limits(max_connections=300)
    started = time.perf_counter()
    async with httpx.AsyncClient(limits=limits, timeout=30.0) as client:
        responses = await asyncio.gather(*(
            client.post(url, json={"identifier": identifier, "tier": "free"})
            for url, _ in requests
        ))
    elapsed = time.perf_counter() - started
    status_counts = {}
    for response in responses:
        status_counts[response.status_code] = status_counts.get(response.status_code, 0) + 1

    print(f"200 responses: {status_counts.get(200, 0)}")
    print(f"429 responses: {status_counts.get(429, 0)}")
    print(f"elapsed seconds: {elapsed:.3f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url_a")
    parser.add_argument("base_url_b")
    parser.add_argument("--identifier", default="two-instance-check")
    args = parser.parse_args()
    asyncio.run(run(args.base_url_a, args.base_url_b, args.identifier))


if __name__ == "__main__":
    main()
