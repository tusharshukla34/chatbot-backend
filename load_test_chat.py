"""
Production-grade load test for Cybrom Course Advisor Chatbot /chat flow.
Simulates 100 concurrent students navigating the full multi-turn conversation.
Measures and reports p50, p90, p95 latency, min/max, throughput, and error rates.
"""

import asyncio
import math
import os
import random
import time
from typing import List, Dict, Any
import httpx

BASE_URL = os.getenv("TARGET_URL", "https://chatbot-backend-a3kk.onrender.com")
CHAT_URL = f"{BASE_URL}/chat"

CONCURRENT_USERS = int(os.getenv("CONCURRENT_USERS", "100"))
ROUNDS = int(os.getenv("ROUNDS", "2"))

PROGRAMS = ["Fullstack Web", "Cyber Security", "Data Programs", "AI-ML", "Digital Marketing"]


def calc_percentile(values: List[float], p: float) -> float:
    """Calculates percentile from list of floats (p between 0.0 and 1.0)."""
    if not values:
        return 0.0
    sorted_v = sorted(values)
    k = (len(sorted_v) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return round(sorted_v[int(k)], 3)
    d0 = sorted_v[int(f)] * (c - k)
    d1 = sorted_v[int(c)] * (k - f)
    return round(d0 + d1, 3)


async def simulate_one_student(client: httpx.AsyncClient, user_id: int) -> Dict[str, Any]:
    session_id = f"load_{user_id}_{int(time.time())}_{random.randint(1000, 9999)}"
    program = random.choice(PROGRAMS)
    overall_start = time.time()
    steps_log = []
    latencies = []

    # Full conversation journey
    messages = [
        f"Student{user_id}",
        f"98{random.randint(10000000, 99999999)}",
        f"student{user_id}_{random.randint(100,999)}@example.com",
        "Graduate",
        program,
    ]

    try:
        for msg in messages:
            t0 = time.time()
            resp = await client.post(
                CHAT_URL,
                json={"session_id": session_id, "message": msg},
                timeout=45.0,
            )
            elapsed = time.time() - t0
            latencies.append(elapsed)
            steps_log.append({"msg": msg, "status": resp.status_code, "sec": round(elapsed, 2)})

            if resp.status_code != 200:
                break

            data = resp.json()
            quick_replies = data.get("quick_replies", [])
            # If subprogram options returned, choose one to complete the full browse
            if quick_replies and quick_replies[0] not in PROGRAMS and quick_replies[0] != "Something else":
                pick = quick_replies[0]
                t1 = time.time()
                resp2 = await client.post(
                    CHAT_URL,
                    json={"session_id": session_id, "message": pick},
                    timeout=45.0,
                )
                elapsed2 = time.time() - t1
                latencies.append(elapsed2)
                steps_log.append({"msg": pick, "status": resp2.status_code, "sec": round(elapsed2, 2)})

        total_time = time.time() - overall_start
        all_ok = all(s["status"] == 200 for s in steps_log)
        return {
            "user_id": user_id,
            "ok": all_ok,
            "total_seconds": round(total_time, 2),
            "latencies": latencies,
            "steps": steps_log,
        }
    except Exception as e:
        return {
            "user_id": user_id,
            "ok": False,
            "error": str(e),
            "latencies": latencies,
            "steps": steps_log,
        }


async def run_load_round(round_num: int):
    print(f"\n========================================================")
    print(f"  ROUND {round_num}: Launching {CONCURRENT_USERS} Concurrent Student Conversations")
    print(f"========================================================")

    limits = httpx.Limits(max_connections=120, max_keepalive_connections=50)
    async with httpx.AsyncClient(limits=limits) as client:
        tasks = [simulate_one_student(client, i) for i in range(CONCURRENT_USERS)]
        results = await asyncio.gather(*tasks)

    successes = [r for r in results if r.get("ok")]
    failures = [r for r in results if not r.get("ok")]

    all_turn_latencies = []
    for r in results:
        all_turn_latencies.extend(r.get("latencies", []))

    total_conv_times = [r["total_seconds"] for r in results if "total_seconds" in r]

    error_rate = (len(failures) / len(results)) * 100.0

    print(f"\n--- Metrics Summary for Round {round_num} ---")
    print(f"Target URL: {CHAT_URL}")
    print(f"Total Completed Conversations: {len(successes)}/{len(results)} ({100 - error_rate:.1f}% Success)")
    print(f"Total Chat Turns Executed:    {len(all_turn_latencies)}")
    print(f"Error Rate:                   {error_rate:.2f}%")

    if all_turn_latencies:
        p50 = calc_percentile(all_turn_latencies, 0.50)
        p90 = calc_percentile(all_turn_latencies, 0.90)
        p95 = calc_percentile(all_turn_latencies, 0.95)
        min_l = min(all_turn_latencies)
        max_l = max(all_turn_latencies)
        avg_l = sum(all_turn_latencies) / len(all_turn_latencies)

        print(f"\nPer-Turn Latency Distribution:")
        print(f"  Min:  {min_l:.3f}s")
        print(f"  p50:  {p50:.3f}s  (Median)")
        print(f"  Avg:  {avg_l:.3f}s")
        print(f"  p90:  {p90:.3f}s")
        print(f"  p95:  {p95:.3f}s")
        print(f"  Max:  {max_l:.3f}s")

    if total_conv_times:
        print(f"\nFull-Journey Duration:")
        print(f"  Avg Full Conversation: {sum(total_conv_times)/len(total_conv_times):.2f}s")
        print(f"  Max Full Conversation: {max(total_conv_times):.2f}s")

    if failures:
        print(f"\nSample Failures ({len(failures)} total):")
        for f in failures[:3]:
            print(f"  User {f['user_id']}: {f.get('error', 'Non-200 HTTP code')}")


async def main():
    print(f"Course Advisor Load Test Suite")
    print(f"Concurrency: {CONCURRENT_USERS} users | Rounds: {ROUNDS} | Target: {CHAT_URL}")
    for r in range(1, ROUNDS + 1):
        await run_load_round(r)
        if r < ROUNDS:
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())