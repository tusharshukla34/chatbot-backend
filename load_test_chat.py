import asyncio
import time
import random
import httpx

BASE_URL = "https://chatbot-backend-a3kk.onrender.com"
CHAT_URL = f"{BASE_URL}/chat"

CONCURRENT_USERS = 100
ROUNDS = 2

PROGRAMS = ["Fullstack Web", "Cyber Security", "Data Programs", "AI-ML", "Digital Marketing"]


async def simulate_one_conversation(client: httpx.AsyncClient, user_id: int) -> dict:
    session_id = f"loadtest_{user_id}_{int(time.time())}_{random.randint(1000,9999)}"
    program = random.choice(PROGRAMS)
    steps_log = []
    overall_start = time.time()

    messages = [
        f"LoadTester{user_id}",
        "9876543210",
        f"loadtest{user_id}@example.com",
        "Graduate",
        program,
    ]

    try:
        for msg in messages:
            start = time.time()
            resp = await client.post(
                CHAT_URL,
                json={"session_id": session_id, "message": msg},
                timeout=60,
            )
            elapsed = time.time() - start
            steps_log.append({"msg": msg, "status": resp.status_code, "seconds": round(elapsed, 2)})
            if resp.status_code != 200:
                break

            data = resp.json()
            quick_replies = data.get("quick_replies", [])
            if quick_replies and quick_replies[0] not in PROGRAMS:
                pick = quick_replies[0]
                start = time.time()
                resp2 = await client.post(
                    CHAT_URL,
                    json={"session_id": session_id, "message": pick},
                    timeout=60,
                )
                elapsed = time.time() - start
                steps_log.append({"msg": pick, "status": resp2.status_code, "seconds": round(elapsed, 2)})

        total_time = time.time() - overall_start
        all_ok = all(s["status"] == 200 for s in steps_log)
        return {"user_id": user_id, "ok": all_ok, "total_seconds": round(total_time, 2), "steps": steps_log}

    except Exception as e:
        return {"user_id": user_id, "ok": False, "error": str(e), "steps": steps_log}


async def run_round(round_num: int):
    async with httpx.AsyncClient() as client:
        tasks = [simulate_one_conversation(client, i) for i in range(CONCURRENT_USERS)]
        results = await asyncio.gather(*tasks)

    successes = [r for r in results if r.get("ok")]
    failures = [r for r in results if not r.get("ok")]
    total_times = [r["total_seconds"] for r in results if "total_seconds" in r]

    print(f"\n=== Round {round_num} ===")
    print(f"Full conversations completed: {len(successes)}/{len(results)}")
    if total_times:
        print(f"Avg full-conversation time: {sum(total_times)/len(total_times):.2f}s | "
              f"Max: {max(total_times):.2f}s | Min: {min(total_times):.2f}s")
    if failures:
        print(f"\nFailed conversations ({len(failures)}):")
        for f in failures:
            print(f"  user {f['user_id']}: {f.get('error', 'non-200 status somewhere')}")
            for step in f.get("steps", []):
                print(f"    -> {step}")


async def main():
    print(f"Load testing full /chat flow at {CHAT_URL}")
    print(f"{CONCURRENT_USERS} concurrent simulated students x {ROUNDS} rounds")
    print("Make sure TEST_MODE=true is set on Render before running this.\n")
    for round_num in range(1, ROUNDS + 1):
        await run_round(round_num)
        await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())