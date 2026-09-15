import asyncio
import time
import httpx

URL = "https://chatbot-backend-a3kk.onrender.com/health"
CONCURRENT_REQUESTS = 20
TOTAL_ROUNDS = 5


async def hit_once(client: httpx.AsyncClient, i: int):
    start = time.time()
    try:
        resp = await client.get(URL, timeout=30)
        elapsed = time.time() - start
        return {"i": i, "status": resp.status_code, "seconds": round(elapsed, 2)}
    except Exception as e:
        elapsed = time.time() - start
        return {"i": i, "status": "ERROR", "error": str(e), "seconds": round(elapsed, 2)}


async def run_round(round_num: int):
    async with httpx.AsyncClient() as client:
        tasks = [hit_once(client, i) for i in range(CONCURRENT_REQUESTS)]
        results = await asyncio.gather(*tasks)

    successes = [r for r in results if r["status"] == 200]
    failures = [r for r in results if r["status"] != 200]
    times = [r["seconds"] for r in results]

    print(f"\n--- Round {round_num} ---")
    print(f"Success: {len(successes)}/{len(results)}")
    print(f"Avg response time: {sum(times)/len(times):.2f}s | Max: {max(times):.2f}s | Min: {min(times):.2f}s")
    if failures:
        print(f"Failures: {failures}")


async def main():
    print(f"Load testing {URL}")
    print(f"{CONCURRENT_REQUESTS} concurrent requests x {TOTAL_ROUNDS} rounds\n")
    for round_num in range(1, TOTAL_ROUNDS + 1):
        await run_round(round_num)
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())