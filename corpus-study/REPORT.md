# Shared-State Interference Audit: asyncio Ecosystem Corpus

**Repos scanned:** 33
**Total shared-state interactions detected:** 21,727  |  **Mediated:** 655 (3.01%)  |  **Unmediated:** 21,072 (96.99%)

## Headline number

> **3.01% of detected shared-state interactions in coroutine code across 33 repos satisfy controlled interference** (655 / 21,727).

This is a *lower-bound-leaning, heuristic* estimate — see Methodology and Limitations below before using it as anything stronger than a directional signal.

**Corpus history:** this is the second expansion of the corpus. The original 22-repo scan (10,724 interactions) has been extended with 10 additional repos (`aio-pika`, `aiocache`, `aiokafka`, `apscheduler`, `asyncmy`, `asyncz`, `elasticsearch-py`, `faust`, `redis-py`, `sqlalchemy`, `tortoise-orm`) plus `fastapi_examples`, targeting the two categories (task/queue systems, database/cache drivers) that were thinnest and most extreme in the first pass. `dramatiq` was dropped from this pass (negligible sample, 1 interaction).

## Per-repo results

| Repo | Category | Files scanned | Interactions | Mediated | Unmediated | % Mediated |
|---|---|---:|---:|---:|---:|---:|
| faust | Task/queue system | 336 | 2,453 | 4 | 2,449 | 0.16% |
| redis-py | DB/cache driver | 157 | 1,715 | 179 | 1,536 | 10.44% |
| aiohttp | Web framework/server | 60 | 1,590 | 4 | 1,586 | 0.25% |
| tortoise-orm | DB/cache driver | 133 | 1,548 | 9 | 1,539 | 0.58% |
| elasticsearch-py | DB/cache driver | 284 | 1,308 | 0 | 1,308 | 0.0% |
| aiokafka | Task/queue system | 68 | 1,249 | 37 | 1,212 | 2.96% |
| kubernetes_asyncio | I/O & networking primitive | 896 | 1,089 | 6 | 1,083 | 0.55% |
| aiobotocore | I/O & networking primitive | 43 | 1,039 | 36 | 1,003 | 3.46% |
| websockets | I/O & networking primitive | 73 | 934 | 15 | 919 | 1.61% |
| apscheduler | Task/queue system | 45 | 898 | 2 | 896 | 0.22% |
| sanic | Web framework/server | 178 | 771 | 148 | 623 | 19.2% |
| aio-pika | Task/queue system | 21 | 723 | 41 | 682 | 5.67% |
| aiomysql | DB/cache driver | 13 | 720 | 6 | 714 | 0.83% |
| quart | Web framework/server | 34 | 627 | 33 | 594 | 5.26% |
| asyncpg | DB/cache driver | 26 | 585 | 5 | 580 | 0.85% |
| aiosonic | I/O & networking primitive | 25 | 554 | 9 | 545 | 1.62% |
| aioredis | DB/cache driver | 12 | 516 | 32 | 484 | 6.2% |
| aiopg | DB/cache driver | 13 | 405 | 8 | 397 | 1.98% |
| fastapi | Web framework/server | 534 | 390 | 0 | 390 | 0.0% |
| databases | DB/cache driver | 17 | 382 | 46 | 336 | 12.04% |
| taskiq | Task/queue system | 83 | 348 | 2 | 346 | 0.57% |
| arq | Task/queue system | 12 | 315 | 0 | 315 | 0.0% |
| sqlalchemy | DB/cache driver | 269 | 297 | 30 | 267 | 10.1% |
| aiocache | DB/cache driver | 13 | 266 | 3 | 263 | 1.13% |
| asyncz | Task/queue system | 145 | 211 | 0 | 211 | 0.0% |
| fastapi_examples | Web framework/server | 461 | 189 | 0 | 189 | 0.0% |
| aiopath | I/O & networking primitive | 12 | 168 | 0 | 168 | 0.0% |
| asyncmy | DB/cache driver | 36 | 147 | 0 | 147 | 0.0% |
| httpx | Web framework/server | 23 | 143 | 0 | 143 | 0.0% |
| motor | DB/cache driver | 16 | 96 | 0 | 96 | 0.0% |
| aiofiles | I/O & networking primitive | 10 | 46 | 0 | 46 | 0.0% |
| pytest-asyncio | Testing infra | 3 | 3 | 0 | 3 | 0.0% |
| asynctest | Testing infra | 7 | 2 | 0 | 2 | 0.0% |

## Breakdown by shared-state kind (aggregate)

| Kind | Total | Mediated | % Mediated |
|---|---:|---:|---:|
| SELF_ATTR | 18,052 | 626 | 3.47% |
| GLOBAL | 3,052 | 27 | 0.88% |
| CLOSURE | 623 | 2 | 0.32% |

**SELF_ATTR** = `self.x` / `cls.x` instance/class attribute access — still the dominant category
(83% of all interactions) and the one most directly analogous to "shared mutable state" in the
classic concurrency sense.

**GLOBAL** = module-level variables *actually assigned/rebound* at module scope (imports excluded).
Grew substantially with this expansion (1,352 → 3,052) mostly due to `faust` and `elasticsearch-py`,
which lean heavily on module-level registries/config.

**CLOSURE** = free variables captured by a nested `async def` / async generator. Still rare, and
still almost never mediated (2 of 623) — closures over shared mutable state in a nested coroutine
are essentially never guarded by a lock in the same function body across this whole corpus.

## Breakdown by repository category

This corpus was deliberately expanded to test whether an earlier, smaller-sample category split
held up. It substantially changed two of the four category estimates — see discussion below.

| Category | Repos | Unmediated interactions | Read-only | Commutative | Destructive |
|---|---:|---:|---:|---:|---:|
| Web framework/server | 6 | 3,525 | 62.7% | 2.5% | 34.8% |
| DB/cache driver | 12 | 7,667 | 67.9% | 1.6% | 30.6% |
| Task/queue system | 7 | 6,111 | 73.3% | 3.2% | 23.5% |
| I/O & networking primitive | 6 | 3,764 | 77.2% | 3.0% | 19.8% |
| Testing infra | 2 | 5 | 100% | 0% | 0% |
| **Pooled** | **33** | **21,072** | **70.3%** | **2.5%** | **27.3%** |

**What changed with the expansion:** the two categories that looked most extreme on a smaller
sample moved sharply toward the middle once more repos were added — DB/cache drivers dropped from
an initial 42.3% (N=6) to 30.6% (N=12), and task/queue systems rose from 15.4% (N=2) to 23.5%
(N=7). The four substantive categories now span 19.8%–34.8%, a materially narrower range than the
15.4%–42.3% spread the first pass suggested. This should be read as evidence that the earlier
estimates for those two categories were undersampled, not as evidence that the current estimates
are themselves saturated — see Limitations.

**Testing infra (5 unmediated interactions total, N=2)** is too small to support any estimate and
is reported for completeness only; it should not be used in prose claims about "testing code."

## Notable repos

- **databases** (55.2% destructive share) and **aiomysql** (52.5%) remain the highest-risk
  individual repos — connection-pool/cursor state mutated across suspension points.
- **aiocache** (45.5%) and **aio-pika** (43.7%) — new additions — are similarly high, reinforcing
  that cache/pool-style state and message-broker channel state both concentrate destructive writes.
- **apscheduler** (42.9%) is high despite being a task/queue-category repo, which is most of why
  that category's average rose from the first pass — a reminder that category means still hide
  large within-category spread (see Caveats).
- **asyncz** (5.2%) and **motor** (2.1%) are the cleanest non-trivial repos in the new corpus.
- **sanic** still has the highest *mediation* rate (19.2%) of any repo, driven by its WebSocket
  frame-processing loop explicitly guarding a shared receive buffer with `self.process_event_mutex`.
- **fastapi**, **fastapi_examples**, **httpx**, **motor**, **aiofiles**, **aiopath**, **asyncmy**,
  **asyncz**, **arq**, **elasticsearch-py**, **pytest-asyncio**, **asynctest** show **0% mediated**.
  As before, for the smallest repos this mostly reflects near-absent `self.x` traffic inside
  `async def` bodies; for the larger ones (fastapi, elasticsearch-py) it means real shared state
  exists but is apparently protected, if at all, by cooperative-scheduling non-preemption rather
  than explicit locks — a legitimate asyncio idiom this scanner cannot verify as safe or unsafe.

## Methodology

1. Cloned each repo (shallow, default branch) and walked every `.py` file, excluding
   `tests/`, `docs/`, `examples/`, `benchmarks/`, and VCS/venv/cache directories.
   (Exception: `fastapi_examples` intentionally scans FastAPI's own examples tree as a separate
   "corpus entry," since example code exercises different patterns than library internals.)
2. Parsed each file with Python's `ast` module and walked a real function-scope chain (not just
   top-level defs) so that `async def` functions nested inside sync functions, methods, or other
   coroutines are all reached exactly once, with correct closure-scope resolution.
3. For every `async def`, computed its **true locals** (params, assignment targets, `for`/`with`
   targets, walrus targets, `except as` names, nested def names) via full-body AST traversal, and
   classified every non-local `Name`/`Attribute` reference as:
   - `SELF_ATTR` — `self.x` / `cls.x`
   - `GLOBAL` — a name actually **assigned** at module scope (not merely imported)
   - `CLOSURE` — a name bound in an enclosing function scope
   - excluded: builtins, imported symbols (immutable bindings from the coroutine's perspective).
4. **Mediation test** (per interaction, lexical/per-function only): an access counts as mediated if
   it occurs textually inside a `with`/`async with` block whose context expression name-matches a
   sync primitive (`lock`, `semaphore`, `condition`, `mutex`, or a direct
   `asyncio.Lock/Semaphore/Event/Queue/Condition(...)` constructor call), **or** it's a call to a
   primitive-safe method (`.acquire`, `.release`, `.wait`, `.set`, `.clear`, `.put`, `.get`, etc.)
   on a name that hints at being a lock/queue/event/condition object.
5. Tallied per repo and aggregated.

Full per-interaction data (file, function, line number, name, kind, mediated/unmediated, reason)
is in `results/<repo>.json` for every repo; `results/_SUMMARY.json` and `results/_REFINED_SUMMARY.json`
have the rollups used above.

## Limitations (read before citing the headline number)

- **Lexical, per-function mediation only, as specified.** A lock acquired by the *caller*
  before invoking this coroutine, or a class-level `async with self._lock:` wrapping the entire
  method one level up, is invisible to this scanner and marked unmediated. Given `self.x` still
  dominates the corpus (83% of interactions), **the true mediation rate is almost certainly higher
  than 3.01% if cross-function mediation were also credited** — read this number as "at least this
  much is *locally, textually* guarded," not "the rest is provably racy."
- **Name-keyword heuristic for identifying primitives**, with the usual false-positive/false-negative
  risk. Spot-checks suggest false positives are rare but not zero, and this risk grows with corpus
  size — the 10 new repos have not been individually spot-checked to the same depth as the original 22.
- **Textual containment ≠ actual protection**, and **single-writer/cooperative-scheduling safety is
  invisible to this method** — both caveats from the original scan apply unchanged and are likely
  the largest source of "unmediated but actually fine" interactions in the corpus.
- **Saturation check, re-run at N=33 (improved, not fully converged).** A running-aggregate check
  of the pooled destructive-write percentage across six repository orderings (the original list
  order plus five random shuffles) shows the curve has flattened substantially compared to N=22:
  the standard deviation of the last ~10 cumulative values (N=24..33) is 0.4–1.1 percentage points
  across orderings, and the full range of those tail values is 1.1–4.0 points — down from a ~5-point
  swing in just the last two repositories added at N=22. All six orderings converge to the same
  final value (26.46%), as they must. This is meaningfully better evidence of stability than the
  original 22-repo estimate had, but it is not perfect convergence — one ordering (a specific random
  shuffle) still shows a ~4-point tail range, so category-level percentages (particularly DB/cache
  drivers and task/queue systems, which moved most during this expansion) should still be read as
  "stabilizing" rather than "settled," pending either more repos or a formal convergence criterion
  (e.g., stop when the last-k-repo swing falls under some fixed threshold).
- **`sqlalchemy` scope caveat:** this is a large monorepo containing both sync and async code
  paths. The scan as configured does not exclude sync-only modules; the 297-interaction count is
  therefore *not* guaranteed to be async-code-only in the same way as smaller, async-first repos.
  This should be verified (e.g., restrict to `lib/sqlalchemy/ext/asyncio` and async dialect files)
  before treating sqlalchemy's 37.7% destructive share as comparable to the other DB-driver entries.
- **`elasticsearch-py` scope caveat:** similarly a mixed sync/async client; `n_python_files_scanned`
  (284) is large relative to its async surface, suggesting some sync-only code may be included.
- **Testing infra category (5 interactions, N=2) is not a meaningful estimate** and should be
  dropped from category-level prose claims or explicitly flagged as underpowered every time it's cited.
- **Name-string bucketing, not per-instance/per-class**, for the destructive/commutative/read-only
  split — see Caveats below; this is an over-approximation in the "flag more, not less" direction.
- **`aiopath` note:** `alexander-akhmetov/aiopath` does not exist on GitHub; substituted the actual
  published `aiopath` project (`alexdelorenzo/aiopath`).
- **`aaugustin/websockets` deduplicated** with `python-websockets/websockets` — same project, GitHub
  org renamed.
- **`dramatiq` dropped** from this pass (1 interaction in the prior scan — statistically vacuous;
  not worth the clone/scan cost at this corpus size).
- Line/module counts reflect a **shallow clone of the default branch on 2026-07-02** (original 22)
  and current default branches as of this expansion; results will shift as these projects evolve.

**Bottom line:** this pipeline gives a reproducible, inspectable *lower bound* on lock/queue/event-
mediated access to shared coroutine state, not a race-detector verdict. Treat 3.01% as "how much of
this corpus's shared-state traffic is *textually, locally* guarded by an explicit asyncio
primitive" — most of the remaining 97% is unverified, not necessarily unsafe.

## Part 3 — Deconstructing the unmediated 97%

As before, the raw mediated/unmediated split treats every unmediated access as equally dangerous,
which isn't true. The scanner tracks the **write form** of every write (full rebind vs.
subscript-insert vs. `+=`-style augmented-assign vs. `.append()`/`.pop()`-style mutating method
calls), and for every distinct shared name asks whether *any* write to that name anywhere in the
repo's async code depends on interleaving order:

- **READ_ONLY** — never written by any scanned coroutine. Exactly SNF-5 territory.
- **COMMUTATIVE** — written, but every write is order-independent (`d[key] = v` on distinct keys,
  `count += 1`, `.append()`/`.add()`-style insertions).
- **DESTRUCTIVE** — at least one write is a full rebind, a non-commutative augmented op, or an
  order-dependent mutating call. Any access to a name in this bucket — including reads — stays in
  the "at risk" pool.

### Result

| Bucket | Count (all accesses) | % of all 21,727 | Unmediated count | Unmediated % of all |
|---|---:|---:|---:|---:|
| READ_ONLY | 15,085 | 69.43% | 14,805 | 68.14% |
| COMMUTATIVE | 540 | 2.49% | 517 | 2.38% |
| DESTRUCTIVE | 6,102 | 28.08% | 5,750 | **26.46%** |

**The refined headline:** **26.46%** of all shared-state interactions in the corpus are unmediated
*and* touch a name with at least one order-dependent write somewhere in the repo — down slightly
from the original 22-repo figure of 29.03%, and consistent with the two-scan agreement seen at the
category level. As a share of just the unmediated pool, that's **27.29%** (5,750 / 21,072).

The "hard problem" — where an over-approximation strategy (e.g., havoc-variable injection) actually
earns its cost — is **5,750 interactions out of 21,727** (26.46% of the corpus), concentrated in
**760 distinct shared names** across all 33 repos (vs. 5,270 distinct names touched overall,
summed per-repo, not deduplicated across repos) — that name-level number, not the access-level
count, is the one to feed into any lock-insertion or verification-fallback strategy.

### Per-repo destructive share (sorted)

| Repo | Total | Read-only | Commutative | Destructive (all) | Unmediated-destructive % of repo |
|---|---:|---:|---:|---:|---:|
| databases | 382 | 127 | 0 | 255 | 55.24% |
| aiomysql | 720 | 330 | 12 | 378 | 52.50% |
| aiocache | 266 | 145 | 0 | 121 | 45.49% |
| aio-pika | 723 | 357 | 35 | 331 | 43.71% |
| apscheduler | 898 | 489 | 24 | 385 | 42.87% |
| aiopg | 405 | 228 | 6 | 171 | 41.73% |
| aiohttp | 1,590 | 915 | 49 | 626 | 39.37% |
| sqlalchemy | 297 | 166 | 0 | 131 | 37.71% |
| websockets | 934 | 559 | 27 | 348 | 37.04% |
| asyncmy | 147 | 92 | 3 | 52 | 35.37% |
| aioredis | 516 | 295 | 16 | 205 | 34.88% |
| sanic | 771 | 407 | 8 | 356 | 34.50% |
| fastapi_examples | 189 | 115 | 11 | 63 | 33.33% |
| redis-py | 1,715 | 1,041 | 46 | 628 | 30.85% |
| aiosonic | 554 | 373 | 6 | 175 | 30.69% |
| asyncpg | 585 | 402 | 16 | 167 | 28.03% |
| quart | 627 | 412 | 13 | 202 | 27.75% |
| httpx | 143 | 107 | 2 | 34 | 23.78% |
| aiokafka | 1,249 | 977 | 19 | 253 | 19.70% |
| tortoise-orm | 1,548 | 1,247 | 13 | 288 | 18.60% |
| fastapi | 390 | 316 | 11 | 63 | 16.15% |
| taskiq | 348 | 281 | 10 | 57 | 15.80% |
| faust | 2,453 | 1,998 | 74 | 381 | 15.37% |
| arq | 315 | 228 | 40 | 47 | 14.92% |
| kubernetes_asyncio | 1,089 | 943 | 30 | 116 | 10.65% |
| elasticsearch-py | 1,308 | 1,153 | 18 | 137 | 10.47% |
| aiobotocore | 1,039 | 877 | 47 | 115 | 10.39% |
| aiofiles | 46 | 42 | 0 | 4 | 8.70% |
| asyncz | 211 | 200 | 0 | 11 | 5.21% |
| motor | 96 | 94 | 0 | 2 | 2.08% |
| aiopath | 168 | 164 | 4 | 0 | 0.0% |
| asynctest | 2 | 2 | 0 | 0 | 0.0% |
| pytest-asyncio | 3 | 3 | 0 | 0 | 0.0% |

**databases** (55.2%), **aiomysql** (52.5%), and **aiocache** (45.5%) have the highest destructive
share — connection-pool, cursor, and cache state are exactly where "last write wins" bugs live if
unguarded. **motor** (2.1%), **asyncz** (5.2%), and **aiopath**/**asynctest**/**pytest-asyncio**
(0%, negligible or thin samples) are the cleanest.

### Caveats on this refinement specifically

- **Name-string bucketing, not per-instance/per-class.** A destructive write to `self._count` in
  class `Foo` makes *every* `self._count` across the whole repo "DESTRUCTIVE," even an unrelated
  read-only `self._count` in class `Bar`. This almost certainly **overcounts** the destructive
  bucket; true per-class dataflow would likely shrink it further.
- **`+=`/`|=` "commutative" ⇒ algebraically commutative, not atomic** — same caveat as before;
  assumes the augmented-assign executes atomically with respect to the event loop, which is true
  for a single `x += 1` but says nothing about a sequence of such statements.
- **Mutating-method commutativity is a heuristic on method name only**, not on actual keys/values —
  e.g. `.append(v)` commutes in final list *membership/size* but not necessarily final *order*.
- **A name with even one destructive write anywhere pulls every access into the risk pool**,
  including accesses in functions that write can't actually reach — deliberately conservative,
  over-approximating in the "flag more, not less" direction.
- **Category means hide substantial within-category spread**, more so after this expansion than
  before: task/queue systems alone range from 5.21% (`asyncz`) to 43.71%/42.87% (`aio-pika`,
  `apscheduler`); DB/cache drivers range from 2.08% (`motor`) to 55.24% (`databases`). Report
  ranges alongside means in any prose that cites a category figure.