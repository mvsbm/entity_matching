"""What every step of one job shares (Job): where its SQL runs, the settings, the method as this file lets it run, and
what the job tells as it goes (Log). Nothing else passes between steps but their results."""
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from er.config import InputError, Pipeline
from er.engine.duckdb import connect, spent
from er.engine.engine import Engine
from er.settings import Settings


def peak_gb() -> float:  # the process's peak resident memory so far (ru_maxrss: bytes on macOS, KB on Linux; Windows: its peak working set)
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):  # PROCESS_MEMORY_COUNTERS
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), *((x, ctypes.c_size_t) for x in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage"))]
        k = ctypes.WinDLL("kernel32")
        k.GetCurrentProcess.restype = wintypes.HANDLE  # a handle is pointer-wide: as a C int it would be cut short on 64 bits
        k.K32GetProcessMemoryInfo.argtypes, k.K32GetProcessMemoryInfo.restype = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD], wintypes.BOOL
        c = Counters(cb=ctypes.sizeof(Counters))
        return c.PeakWorkingSetSize / 1e9 if k.K32GetProcessMemoryInfo(k.GetCurrentProcess(), ctypes.byref(c), c.cb) else 0.0
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1e9 if sys.platform == "darwin" else 1e6)


@dataclass
class Log:
    """What a job tells as it goes. `steps`: each step's facts as it ends (steps.json), `echo` called with each, for
    people; `told(done, total, unit, **facts)` as a long step goes; `notes`: what the steps detected or fixed, for the
    summary, never a record's value; `examples`: notes that quote one (the summary and qa.md show them, report.txt
    doesn't)."""
    echo: Callable[[dict], None] | None = None
    told: Callable[..., None] | None = None
    steps: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    spent: dict = field(default_factory=spent)  # the comparison functions' time when the last step ended

    def done(self, name: str, big_o: str, filled: str, t: float, **facts: object) -> None:
        """A step ended: its Big-O, with the numbers filled in, its seconds since `t`, the peak memory so far, its facts,
        and the comparison functions' time since the step before (compared)."""
        now = spent()
        was = lambda k: self.spent.get(k, (0, 0, 0, 0))
        compared = {k: dict(cpu=round(s - was(k)[0], 4), values=int(n - was(k)[1]), calls=int(c - was(k)[2]), wall=round(w - was(k)[3], 4))
                    for k, (s, n, c, w) in now.items() if n > was(k)[1]}
        self.spent = now
        self.steps.append(dict(step=name, big_o=big_o, filled=filled, seconds=round(time.perf_counter() - t, 2),
                               peak_memory_gb=round(peak_gb(), 2), **facts, **({"compared": compared} if compared else {})))
        if self.echo:
            self.echo(self.steps[-1])


@dataclass
class Job:
    """One job's engine, settings and method (`pipeline`: as the records file lets it run, once load has seen it), and
    its log. The steps read their tables from the engine by the names each step's docstring gives."""
    engine: Engine
    settings: Settings
    pipeline: Pipeline
    log: Log

    @property
    def uid(self) -> str:  # the ID column
        return self.settings.data.unique_id

    @property
    def l(self) -> str:  # a pair's two IDs
        return f"{self.uid}_l"

    @property
    def r(self) -> str:
        return f"{self.uid}_r"

    def count(self, sql: str) -> int:  # the rows of a table, or of `table WHERE …`
        return self.engine.value(f"SELECT count(*) FROM {sql}")

    def columns(self, table: str = "records") -> set[str]:
        return {c[0] for c in self.engine.rows(f"DESCRIBE {table}")}


def start(settings: Settings, pipeline: Pipeline, echo: Callable[[dict], None] | None = None, told: Callable[..., None] | None = None) -> Job:
    """A job on an engine of its own (config/settings.toml [compute]): the method checked first, so a wrong value stops it
    before any work."""
    if {pipeline.rules.resolver.method, pipeline.fs.resolver.method} != {"connected_components"}:
        raise InputError("the run clusters by connected components only; the pipeline asks for "
                         f"{pipeline.rules.resolver.method} (rules) and {pipeline.fs.resolver.method} (model)",
                         fix='set resolver = { method = "connected_components" } in both stages of the pipeline')
    return Job(connect(settings.compute), settings, pipeline, Log(echo, told))


@dataclass
class Ran:
    """What a job did, as its write, its reports and its caller read it: the job (engine, settings, method, log), and
    the facts its steps returned. Built by the job once its steps ran; the report step adds qa's tables."""
    job: Job
    n: int = 0                                # the records resolved (an increment: every record of the run)
    added: int | None = None                  # an increment's new records (0: nothing new); None: a full run
    model: dict | None = None                 # the model as fitted (state/model.json)
    scoring: dict | None = None               # the model with u from this file: what the scores used
    basis: dict = field(default_factory=dict)  # what an increment needs to tell whether those u went stale
    disabled: list[str] = field(default_factory=list)  # what of the method the file's fields can't run
    present: dict = field(default_factory=dict)  # each field the file holds, and its source columns
    unmapped: object = None                   # the file's columns no field reads, on a sample
    gated: object = None                      # the oversized blocks checked, and what was decided (a frame)
    plan: object = None                       # the budget's pairs per rule and generator (a frame); an increment has none
    classifier: object = None                 # each record's kind (er.kind); None: the method doesn't ask
    placeholders: dict[str, list[str]] = field(default_factory=dict)  # each field's values read as missing
    inputs: list[dict] = field(default_factory=list)  # the files read: path, bytes, SHA-256
    part: int = 0                             # the part written: 0 a full run's, an increment's one past the run's highest
    listed: int = 0                           # the pairs the keys listed
    rule_seconds: dict[str, float] = field(default_factory=dict)  # each rule's join
    config: str = ""                          # the run's fingerprint: what an increment needs the full run's to be (steps.write.run_config)
    tables: dict = field(default_factory=dict)  # qa's tables, the summary first, once the report step built them

    engine = property(lambda self: self.job.engine)
    settings = property(lambda self: self.job.settings)
    pipeline = property(lambda self: self.job.pipeline)
    uid = property(lambda self: self.job.uid)
    l = property(lambda self: self.job.l)
    r = property(lambda self: self.job.r)
    steps = property(lambda self: self.job.log.steps)
    notes = property(lambda self: self.job.log.notes)
    examples = property(lambda self: self.job.log.examples)

    @property
    def fields(self) -> list[str]:  # the logical fields of [columns]
        from er.settings import SPECIAL
        return [f for f in self.settings.columns if f not in SPECIAL]

    def columns(self) -> set[str]:  # the records table's columns
        return self.job.columns()

    def count(self, sql: str) -> int:
        return self.job.count(sql)

    def capacity(self) -> int:
        from er.steps.budget import capacity
        return capacity(self.engine)

    def spill_room(self) -> float:
        return self.engine.spill_room()
