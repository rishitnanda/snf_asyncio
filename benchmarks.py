import asyncio

# ============================================================
# SCALED BENCHMARKS  (Option A — larger asyncio workloads)
# ============================================================

# CATEGORY 1: TASK LIFECYCLE & INTERLEAVING

async def b1_structured_task_group_scaled(fail_trigger: bool):
    """
    SCALED: 8 workers instead of 2.
    8! = 40320 possible orderings forces deep MBQI instantiation.
    Worker 1 raises on fail_trigger; TaskGroup cancels ALL siblings.
    Property: if fail_trigger=1 then shared_count=0.
    """
    shared_state = {"count": 0}

    async def worker(worker_id: int, delay: float):
        if worker_id == 1 and fail_trigger:
            raise ValueError("Simulated worker failure")
        await asyncio.sleep(delay)
        shared_state["count"] += 1

    try:
        async with asyncio.TaskGroup() as tg:
            # 8 workers with distinct delays so ordering is deterministic
            # but naive encoder doesn't know that
            tg.create_task(worker(1, 0.10))
            tg.create_task(worker(2, 0.20))
            tg.create_task(worker(3, 0.30))
            tg.create_task(worker(4, 0.40))
            tg.create_task(worker(5, 0.50))
            tg.create_task(worker(6, 0.60))
            tg.create_task(worker(7, 0.70))
            tg.create_task(worker(8, 0.80))
    except* ValueError:
        pass

    return shared_state["count"]


async def b2_fire_and_forget(fail_trigger: bool):
    """
    UNCHANGED — kept because naive returns SAT (correctness gap finding).
    Naive encoding cannot prove the property without timing constraint.
    """
    state = {"processed": False}

    async def background_job():
        await asyncio.sleep(0.2)
        state["processed"] = True

    task = asyncio.create_task(background_job())
    await asyncio.sleep(0.1)

    if fail_trigger:
        task.cancel()

    try:
        await task
    except asyncio.CancelledError:
        pass

    return state["processed"]


async def b3_mutex_contention_scaled(num_tasks: int = 10):
    """
    SCALED: 10 tasks instead of 3.
    10! = 3,628,800 possible lock acquisition orderings.
    Naive encoder must quantify over all permutations.
    Property: shared_resource = num_tasks (no lost updates under mutex).
    """
    lock = asyncio.Lock()
    shared_resource = 0

    async def critical_section():
        nonlocal shared_resource
        async with lock:
            current = shared_resource
            await asyncio.sleep(0.01)
            shared_resource = current + 1

    tasks = [asyncio.create_task(critical_section()) for _ in range(num_tasks)]
    await asyncio.gather(*tasks)
    return shared_resource


async def b4_event_broadcast_scaled():
    """
    SCALED: 12 waiters instead of 4.
    12! = 479,001,600 possible wakeup orderings.
    Naive encoder quantifies over all orderings.
    Property: len(results) = 12.
    """
    event = asyncio.Event()
    results = []

    async def waiter(idx: int):
        await event.wait()
        results.append(idx)

    tasks = [asyncio.create_task(waiter(i)) for i in range(12)]
    await asyncio.sleep(0.05)
    event.set()
    await asyncio.gather(*tasks)
    return len(results)


async def b5_race_and_timeout_scaled():
    """
    SCALED: 5 nested wait_for calls in sequence (2^5=32 outcome branches).
    Each service has a different sleep time; each timeout is a different value.
    Naive encoder must branch on all 32 combinations.
    Property: exactly the services with sleep < timeout return SUCCESS.
    """
    results = {}

    async def service(name: str, sleep: float):
        await asyncio.sleep(sleep)
        return "SUCCESS"

    # (name, sleep_time, timeout_val) — structured knows outcome statically
    races = [
        ("s1", 0.10, 0.20),   # completes  (0.10 < 0.20)
        ("s2", 0.30, 0.20),   # times out  (0.30 > 0.20)
        ("s3", 0.05, 0.10),   # completes  (0.05 < 0.10)
        ("s4", 0.40, 0.15),   # times out  (0.40 > 0.15)
        ("s5", 0.08, 0.12),   # completes  (0.08 < 0.12)
    ]

    for name, sleep, timeout in races:
        try:
            results[name] = await asyncio.wait_for(service(name, sleep), timeout=timeout)
        except asyncio.TimeoutError:
            results[name] = "TIMEOUT"

    # Expected: s1=SUCCESS, s2=TIMEOUT, s3=SUCCESS, s4=TIMEOUT, s5=SUCCESS
    successes = sum(1 for v in results.values() if v == "SUCCESS")
    return successes   # should always be 3


async def b6_producer_consumer_queue_scaled():
    """
    SCALED: Queue(maxsize=3), 8 items, 2 producers, 2 consumers.
    Multiple producers/consumers create much deeper interleaving.
    Naive encoder must track all put/get interleavings across 4 tasks.
    Property: all 8 items are consumed exactly once.
    """
    queue = asyncio.Queue(maxsize=3)
    state = []

    async def producer(start: int, count: int):
        for i in range(start, start + count):
            await queue.put(f"item_{i}")

    async def consumer(target: int):
        collected = 0
        while collected < target:
            item = await queue.get()
            state.append(item)
            queue.task_done()
            collected += 1

    # 2 producers: p1 puts items 0-3, p2 puts items 4-7
    # 2 consumers: each collects 4 items
    p1 = asyncio.create_task(producer(0, 4))
    p2 = asyncio.create_task(producer(4, 4))
    c1 = asyncio.create_task(consumer(4))
    c2 = asyncio.create_task(consumer(4))
    await asyncio.gather(p1, p2, c1, c2)
    return len(state)   # should always be 8


async def b7_readonly_broadcast_unmediated():
    """
    NEW: unmediated read-only broadcast, 8 readers.
    No asyncio.Event, no lock, no mediator of any kind -- readers run
    fully unordered relative to one another (unlike b4, there is no
    "all waiters unblock atomically" structural guarantee).
    Property: every reader observes config["x"] = 42.
    Since config is immutable (no writer ever mutates it) and there is
    no mediating happens-before edge, the read-only invariance lemma
    applies: the outcome is independent of scheduling order, so no
    case-split over the 8! orderings is required at all.
    """
    config = {"x": 42}
    results = []

    async def reader(idx: int):
        # small unordered delay -- no primitive establishes any
        # relative ordering between readers
        await asyncio.sleep(0.01 * (idx % 3))
        results.append(config["x"])

    tasks = [asyncio.create_task(reader(i)) for i in range(8)]
    await asyncio.gather(*tasks)

    return all(v == 42 for v in results)   # should always be True


# ============================================================
# OPTION B — Pigeonhole Principle benchmarks
# ============================================================

def php_naive_description(n: int) -> str:
    """
    PHP(n): n+1 pigeons, n holes.
    Naive: universally quantified — solver must prove no valid assignment exists.
    This is the canonical MBQI stress test; instability grows sharply with n.
    """
    return f"PHP({n}): {n+1} pigeons, {n} holes — naive AUFLIA encoding"


def php_structured_description(n: int) -> str:
    return f"PHP({n}): {n+1} pigeons, {n} holes — structured QF_LIA encoding"