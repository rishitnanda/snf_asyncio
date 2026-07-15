# Shared-State Interference Audit: asyncio Ecosystem Corpus

**Repos scanned:** 33
**Total shared-state interactions detected:** 20,422  |  **Mediated:** 619 (3.03%)  |  **Unmediated:** 19,803 (96.97%)

## Headline number

> **3.03% of detected shared-state interactions in coroutine code across 33 repos satisfy controlled interference** (619 / 20,422).

This is a *lower-bound-leaning, heuristic* estimate — see Methodology and Limitations below before using it as anything stronger than a directional signal.

**Corpus history:** this is the second expansion of the corpus (22 → 33 repos), further refined by a scope-scan audit that restricted `sqlalchemy`, `elasticsearch-py`, and `redis-py` to their actual async submodules, and excluded `websockets`'s sync/Trio backends and `kubernetes_asyncio`'s auto-generated model directory. This is the run those fixes are reflected in; it supersedes the earlier 21,727-total report, which predates the `redis-py`/`sqlalchemy`/`elasticsearch-py` scoping and the `websockets`/`kubernetes_asyncio` exclusions.

## Per-repo results

| Repo | Files scanned | Interactions | Mediated | % Mediated | Scoped? |
|---|---:|---:|---:|---:|---|
| faust | 336 | 2,453 | 4 | 0.16% | |
| aiohttp | 60 | 1,590 | 4 | 0.25% | |
| tortoise-orm | 133 | 1,548 | 9 | 0.58% | |
| redis-py | 22 | 1,359 | 169 | 12.44% | scoped: `redis/asyncio` |
| aiokafka | 68 | 1,249 | 37 | 2.96% | |
| kubernetes_asyncio | 128 | 1,089 | 6 | 0.55% | excluded: `client/models`, `test` |
| aiobotocore | 43 | 1,039 | 36 | 3.46% | |
| sanic | 178 | 771 | 148 | 19.20% | |
| aio-pika | 21 | 723 | 41 | 5.67% | |
| aiomysql | 13 | 720 | 6 | 0.83% | |
| websockets | 62 | 721 | 0 | 0.0% | excluded: `sync`, `trio` |
| elasticsearch-py | 47 | 619 | 0 | 0.0% | scoped: `elasticsearch/_async` |
| quart | 34 | 627 | 33 | 5.26% | |
| asyncpg | 26 | 585 | 5 | 0.85% | |
| aiosonic | 25 | 554 | 9 | 1.62% | |
| aioredis | 12 | 516 | 32 | 6.20% | |
| aiopg | 13 | 405 | 8 | 1.98% | |
| fastapi | 534 | 390 | 0 | 0.0% | |
| databases | 17 | 382 | 46 | 12.04% | |
| taskiq | 83 | 348 | 2 | 0.57% | |
| arq | 12 | 315 | 0 | 0.0% | |
| sqlalchemy | 11 | 250 | 19 | 7.60% | scoped: `ext/asyncio` + async dialects |
| aiocache | 13 | 266 | 3 | 1.13% | |
| asyncz | 145 | 211 | 0 | 0.0% | |
| fastapi_examples | 461 | 189 | 0 | 0.0% | |
| aiopath | 12 | 168 | 0 | 0.0% | |
| asyncmy | 36 | 147 | 0 | 0.0% | |
| httpx | 23 | 143 | 0 | 0.0% | |
| motor | 16 | 96 | 0 | 0.0% | |
| aiofiles | 10 | 46 | 0 | 0.0% | |
| pytest-asyncio | 3 | 3 | 0 | 0.0% | |
| asynctest | 7 | 2 | 0 | 0.0% | |

## Breakdown by shared-state kind (aggregate)

| Kind | Total | Mediated | % Mediated |
|---|---:|---:|---:|
| SELF_ATTR | 17,203 | 590 | 3.43% |
| GLOBAL | 2,628 | 27 | 1.03% |
| CLOSURE | 591 | 2 | 0.34% |

## Methodology

1. Cloned each repo (shallow, default branch) and walked every `.py` file, excluding `tests/`, `docs/`, `examples/`, `benchmarks/`, and VCS/venv/cache directories.
2. Parsed each file with Python's `ast` module and walked a real function-scope chain so nested `async def` functions are reached exactly once, with correct closure-scope resolution.
3. Classified each interaction as **mediated** (inside an `async with`/method call on an `asyncio.Lock`/`Queue`/`Event`/`Semaphore`/`Condition` in the same function) or **unmediated**, per-function only (no cross-function call-graph analysis).
4. Deconstructed the unmediated bucket (`refine.py`) by write-form into **READ_ONLY** (SNF-5), **COMMUTATIVE**, and **DESTRUCTIVE**, then split DESTRUCTIVE (`branch_check.py`) by whether the flagged name gates a branch, and if so, whether that branch is bounded (If/IfExp/BoolOp/comprehension) or unbounded (While).

## Part 3 — Deconstructing the unmediated 97%

### Result

| Bucket | Count (all accesses) | % of all 20,422 | Unmediated count | Unmediated % of all |
|---|---:|---:|---:|---:|
| READ_ONLY | 14,183 | 69.45% | 13,924 | 68.18% |
| COMMUTATIVE | 507 | 2.48% | 485 | 2.37% |
| DESTRUCTIVE | 5,732 | 28.07% | 5,394 | **26.41%** |

**The refined headline:** **26.41%** of all shared-state interactions in the corpus are unmediated *and* touch a name with at least one order-dependent write somewhere in the repo.

## Part 4 — Definition 13/15 split of the destructive bucket (`branch_check.py`)

| Sub-bucket | Interactions | % of flagged | Distinct names |
|---|---:|---:|---:|
| Flagged-data (Prop. 12 applies) | 2,007 | 35.01% | 354 |
| Flagged-control, bounded-path (Prop. 13 applies) | 3,439 | 60.00% | 360 |
| Flagged-control, unbounded-loop (OPEN) | 286 | 4.99% | 24 |

Within flagged-control specifically: 92.32% bounded-path, 7.68% unbounded-loop-gated.

## Part 5 — Thread-offloading overlap (`thread_overlap_check.py`)

Of 5,394 unmediated-destructive interactions, **43 (0.8%)** occur inside a function that also calls `run_in_executor` or constructs a `ThreadPoolExecutor`/`Thread` — a lower bound (same-function only, no call-graph analysis). Concentrated in `aiohttp`, `taskiq`, and `asyncz`; 7 of 33 repos show any thread-offloading overlap at all.

## Part 6 — `eager_task_factory` incidence (`eager_factory_check.py`)

**Zero** of 33 repos reference `asyncio.eager_task_factory` in any form (literal reference, import, or `set_task_factory`/`Runner` argument).

## Limitations

- **Name-string bucketing, not per-instance/per-class**, for the destructive/commutative/read-only split. A destructive write to `self._count` in one class makes *every* `self._count` across the whole repo "DESTRUCTIVE," even an unrelated read-only `self._count` in another class. This is disclosed as a design limitation in `refine.py`, and is deliberately conservative in the "flag more, not less" direction.

- **Confirmed, unresolved contamination in four repos: `aiohttp`, `faust`, `sanic`, `tortoise-orm`.** `scope_contamination_check.py` found direct, named collisions between a sync-only file's write and an async-side read-only candidate of the same `(kind, name)` in these repos (25, 16, 10, and 17 colliding names respectively). Unlike `sqlalchemy`/`elasticsearch-py`/`redis-py` (genuine parallel sync/async directory trees, fixed via `REPO_ASYNC_SCOPE`) and `websockets`/`kubernetes_asyncio` (isolable sync-only/generated subtrees, fixed via `REPO_ASYNC_EXCLUDE`), these four repos' collisions are **not** confined to an isolable subtree — the colliding names (`self.name`, `self.app`, `self.loop`, `self.config`, `self.headers`, `self.query`, `self.pk`, `self.fields`, `self.model`, etc.) are short, generic attribute names reused across unrelated classes scattered throughout otherwise-legitimate async-first source, not a sync-mirror-of-async architecture. No `REPO_ASYNC_SCOPE`/`REPO_ASYNC_EXCLUDE` path restriction can separate the noise from the signal here without either excluding real async-relevant files or leaving the contamination in place. **These four repos' DESTRUCTIVE-bucket counts should be treated as upper bounds, not verified figures**, pending a class-qualified `(kind, name)` scheme in `scan.py` (tracking `SELF_ATTR` names by enclosing class rather than bare attribute string) — a scan.py-level change, not a config-dict fix, and one that will shift numbers for more than just these four repos.

- **13 additional repos show high sync-only file percentages but no confirmed name collision** (`scope_conflation_check.py` flagged >30% sync-only files; `scope_contamination_check.py` found zero actual collisions for these) — high sync-file share alone does not imply contamination, and these are correctly left unscoped.

- **`+=`/`|=` "commutative" ⇒ algebraically commutative, not atomic.** Assumes the augmented-assign executes atomically with respect to the event loop.

- **Mutating-method commutativity is a heuristic on method name only**, not on actual keys/values.

- **A name with even one destructive write anywhere pulls every access into the risk pool**, including accesses in functions that write can't actually reach — deliberately conservative.

- **Definition 15's bounded/unbounded split is a syntactic proxy** (a name appearing in ANY `While`-test anywhere in the repo is always counted as unbounded), not a verified check against the precise condition — an upper bound on Proposition 13's practical coverage, not a measured count.

- **Testing infra category (5 interactions total) is not a meaningful estimate.**

**Bottom line:** this pipeline gives a reproducible, inspectable *lower bound* on lock/queue/event-mediated access to shared coroutine state, not a race-detector verdict. Treat 3.03% as "how much of this corpus's shared-state traffic is *textually, locally* guarded by an explicit asyncio primitive" — most of the remaining 97% is unverified, not necessarily unsafe, and four repos' destructive-share figures carry a known, unresolved contamination risk documented above.