"""
IR for the SNF source-to-SMT pipeline.

A Program is a set of Coroutines. Each Coroutine is a linear sequence of Ops
in program order (the order they'd execute if run alone, i.e. arrival order
at each yield/await point). Ops reference SyncObjects (Lock/Queue/Event) by
name; the encoder resolves contention over shared SyncObjects into the
SNF-structured disjunction (FIFO ordering constraints), per SNF-4.
"""

from dataclasses import dataclass, field
from enum import Enum, auto


class OpKind(Enum):
    WAIT_FOR = auto()      # asyncio.wait_for(coro, timeout=...) / compat.wait_for(...)
    ACQUIRE = auto()      # async with lock: / await lock.acquire()
    RELEASE = auto()      # implicit end of "async with lock" block / lock.release()
    Q_GET = auto()        # await queue.get()
    Q_PUT = auto()        # queue.put_nowait(x) / await queue.put(x)
    EV_WAIT = auto()       # await event.wait()
    EV_SET = auto()        # event.set()
    GENERIC_AWAIT = auto()  # any other await we don't model precisely


class SyncKind(Enum):
    LOCK = auto()
    QUEUE = auto()
    EVENT = auto()


@dataclass
class Op:
    kind: OpKind
    sync_obj: str          # name of the Lock/Queue/Event this op touches, or "" if none
    coro: str               # owning coroutine name
    seq: int                # program-order position within the coroutine
    line: int = -1
    note: str = ""


@dataclass
class Coroutine:
    name: str
    ops: list = field(default_factory=list)  # list[Op] in program order


@dataclass
class Program:
    sync_objects: dict = field(default_factory=dict)   # name -> SyncKind
    coroutines: dict = field(default_factory=dict)     # name -> Coroutine
    wait_for_sites: list = field(default_factory=list)  # list[dict]: coro, line, handled_locally
    unresolved_refs: list = field(default_factory=list)  # list[dict]: sync-like names whose
                                                            # origin couldn't be resolved (passed
                                                            # in as an argument, built via a
                                                            # factory, imported from elsewhere)
    task_refs: dict = field(default_factory=dict)  # (class_scope, attr) -> callee_name
    spawn_multiplicity: dict = field(default_factory=dict)  # coro_name -> int, detected
                                                               # from create_task/gather/loop
                                                               # patterns spawning that coroutine
                                                               # concurrently >1 time (default 1)
    assumed_concurrent: set = field(default_factory=set)  # coro_names given multiplicity via
                                                            # the --assume-public-concurrent
                                                            # opt-in heuristic, NOT detected from
                                                            # source -- always reported separately
    coro_name_collisions: dict = field(default_factory=dict)  # bare_name -> list of distinct
                                                                 # class_scopes (or None for
                                                                 # module-level) that define a
                                                                 # coroutine with that name.
                                                                 # Populated whenever a bare name
                                                                 # is ambiguous across >1 class --
                                                                 # see extractor.py's docstring on
                                                                 # why this is flagged rather than
                                                                 # silently resolved (limitation #9)

    def add_sync(self, name, kind: SyncKind):
        if name not in self.sync_objects:
            self.sync_objects[name] = kind

    def coro(self, name) -> Coroutine:
        if name not in self.coroutines:
            self.coroutines[name] = Coroutine(name=name)
        return self.coroutines[name]