"""Each example (graal-export/examples/) still shows what its comment says: the conversion examples by their shape, the limits by what
the translation refuses or makes opaque, and the concurrency examples by their kill sets, the reasons their methods are opaque, whether
their item is published, and which of their locks and volatile accesses can go.

The exports come from `graal-export/suite` (or `make suite`); without them these
checks are skipped.
"""

from pathlib import Path

import pytest

from dataclasses import replace

from cthu import prelude
from cthu.ir import Program, Structure
from cthu.ssu import check
from effects.blockers import blockers
from effects.elide import elidable
from effects.kills import ANY, kills
from effects.signatures import PARTITIONERS, analyse, no_analysis
from graal.graal_import import PointsToFacts, load, load_facts
from graal2ct.translate import Translation

SUITE = Path(__file__).parents[2] / "graal-export" / "out" / "suite"


def looping(s: Structure) -> set[str]:
    """The λs on a loop: those that jump or branch, through others of the
    method's λs, back to themselves. A call of the method itself isn't a loop."""
    refs = {lam.name: {i.op for i in lam.body if i.type == s.name and i.op != "run"} for lam in s.lambdas}  # "run": a method's entry
    found = set()
    for start in refs:
        seen, work = set(), list(refs[start])
        while work:
            name = work.pop()
            if name == start:
                found.add(start)
                break
            if name not in seen:
                seen.add(name)
                work.extend(refs.get(name, ()))
    return found


def translate(example: str, partition: str) -> tuple[Program, Translation]:
    """The example's `demo` method, under the partitioning; the object
    partitionings read the export with allocation sites."""
    path = SUITE / (f"{example}.allocsens.json" if partition.startswith("object") else f"{example}.json")
    if not path.exists():
        pytest.skip(f"{path} is missing: run graal-export/suite")
    facts, graphs = load(path)
    effects = no_analysis() if partition == "none" else analyse(facts, PARTITIONERS[partition](facts))
    translation = Translation(graphs, effects)
    program = translation.translate([k for k in sorted(graphs) if ".demo(" in k or k.endswith(".demo")])
    assert not check(program) + prelude.check(program, prelude.load()), (example, partition)
    return program, translation


def demo(program: Program) -> Structure:
    assert len(program.structures) == 1, [s.name for s in program.structures]
    return program.structures[0]


def heaps(params: list[tuple[str, str]]) -> list[str]:
    return [n for n, t in params if t == "heap"]


def ops(s: Structure) -> list[str]:
    return [i.op for lam in s.lambdas for i in lam.body]


def call_of(s: Structure, callee: str):
    """The call of the method whose structure name contains `callee`."""
    defs = {o: i for lam in s.lambdas for i in lam.body for o in i.outs}
    return next(i for lam in s.lambdas for i in lam.body
                if i.op == "call" and i.ins[0] in defs and callee in defs[i.ins[0]].type)


def check_suite_conversion() -> None:
    """Each conversion example has the shape its comment describes."""
    s = demo(translate("conversion.PureArithmetic", "field")[0])
    assert not heaps(s.lambdas[0].params)
    assert len(heaps(demo(translate("conversion.PureArithmetic", "none")[0]).lambdas[0].params)) == 1

    s = demo(translate("conversion.StaticFieldUpdate", "field")[0])
    assert [o for o in ops(s) if "static" in o] == ["getstatic_0", "setstatic_0"], ops(s)

    s = demo(translate("conversion.NullCheck", "field")[0])
    assert any(lam.exit == "throws" and "exception" in [i.op for i in lam.body] for lam in s.lambdas)
    s = demo(translate("conversion.ReceiverField", "field")[0])
    assert [lam.name for lam in s.lambdas] == ["run"] and "exception" not in ops(s)

    s = demo(translate("conversion.IfElse", "field")[0])
    arms = [lam for lam in s.lambdas if any(i.op.startswith("setstatic") for i in lam.body)]
    assert len(arms) == 2 and {i.field for lam in arms for i in lam.body if i.field} == \
        {"conversion.IfElse.hits", "conversion.IfElse.misses"}
    assert any(lam.name.startswith("frame_") for lam in s.lambdas)

    s = demo(translate("conversion.ValueMerge", "field")[0])
    assert not heaps(s.lambdas[0].params)
    assert any(lam.name not in ("run",) and not lam.name.startswith("frame_") and lam.params for lam in s.lambdas)

    s = demo(translate("conversion.CountingLoop", "field")[0])
    assert looping(s) and not heaps(s.lambdas[0].params)
    s = demo(translate("conversion.LoopOverField", "field")[0])
    loop = looping(s)
    assert loop and any(i.op == "getstatic_0" for lam in s.lambdas if lam.name in loop for i in lam.body)

    s = demo(translate("conversion.StaticCall", "field")[0])
    assert call_of(s, "bump").ins[2:] == ["h_count"] and len(heaps(s.lambdas[0].params)) == 2
    s = demo(translate("conversion.PureCall", "field")[0])
    assert call_of(s, "fib").ins[1:] == ["p0"]
    assert len(call_of(demo(translate("conversion.PureCall", "none")[0]), "fib").ins) == 3

    program, _ = translate("conversion.VirtualCall", "field")
    assert any(m.startswith("one of") and m.count("grow") == 2 for m in program.externals.values())
    assert len(call_of(demo(program), "dispatch").ins) == 4  # the closure, the receiver, h_radius, h_side

    s = demo(translate("conversion.CatchException", "field")[0])
    assert any("instanceof_0" in [i.op for i in lam.body] for lam in s.lambdas)
    s = demo(translate("conversion.ThrowException", "field")[0])
    assert any(lam.exit == "throws" and any(i.op == "move" and i.outs == ["exc"] for i in lam.body)
               for lam in s.lambdas)
    s = demo(translate("conversion.NewObject", "field")[0])
    assert "new_0" in ops(s) and {"init_0", "init_1"} <= set(ops(s))
    s = demo(translate("conversion.ArrayElement", "field")[0])
    assert {"aget_int", "aset_int", "length"} <= set(ops(s))
    print("ok   suite: each conversion example has the shape its comment describes")


def check_suite_limits() -> None:
    """The switch is refused; the native call makes the method take every token. The lock
    and the volatile read translate: taking the lock and the volatile read acquire every
    token before the field is read, leaving the lock releases every token after it is
    written."""
    program, translation = translate("limits.Switch", "field")
    assert not program.structures and any("IntegerSwitch" in why for why in translation.refused.values()), translation.refused
    s = demo(translate("limits.Synchronized", "field")[0])
    sync = [i.op for i in s.lambdas[0].body if i.op in ("acquire", "release", "getstatic_0", "setstatic_0")]
    tokens = len(heaps(s.lambdas[0].params))
    assert sync == ["acquire"] * tokens + ["getstatic_0", "setstatic_0"] + ["release"] * tokens, sync
    s = demo(translate("limits.VolatileField", "field")[0])
    sync = [i.op for i in s.lambdas[0].body if i.op in ("acquire", "release", "getstatic_0")]
    assert sync == ["acquire"] * len(heaps(s.lambdas[0].params)) + ["getstatic_0"], sync
    facts, graphs = load(SUITE / "limits.OpaqueCall.json")
    effects = analyse(facts, PARTITIONERS["field"](facts))
    s = demo(translate("limits.OpaqueCall", "field")[0])
    assert len(heaps(s.lambdas[0].params)) == len(effects.partitions)
    print("ok   suite: the switch is refused, an opaque call takes every token, a lock and a volatile read acquire and release")


#: example → its method that synchronizes, and what a call to it may write (as Graal is told):
#: everything for a lock or volatile field another thread may reach, nothing but the method's own
#: writes for one only this thread reaches. A kill set can't tell Graal "everything another thread
#: may touch", so a call that synchronizes with another thread kills everything, even if
#: the token form lets loads of memory only this thread reaches pass it. The methods reaching code
#: without facts (AcrossAtomicLocal's helper) kill everything for that reason.
SYNCHRONIZING_CALLS = {
    "concurrency.AcrossLocalMonitor": ("$Tally.add(", ("concurrency.AcrossLocalMonitor$Tally.count",)),
    "concurrency.AcrossLockLocal": (".logged(", ANY),
    "concurrency.AcrossLockSharedBlocks": (".logged(", ANY),
    "concurrency.FinalAcrossLock": (".logged(", ANY),
    "concurrency.AcrossAcquireLocal": (".poll(", ANY),
    "concurrency.AcrossAcquireSharedBlocks": (".poll(", ANY),
    "concurrency.AcrossRelease": (".publish(", ANY),
    "concurrency.AcquireInMethodBlocks": (".demo(", ANY),
    "concurrency.ReleaseInMethod": (".demo(", ANY),
    "concurrency.DeadStoreAcrossAcquire": (".demo(", ANY),
    "concurrency.DeadStoreAcrossReleaseKeeps": (".demo(", ANY),
    "concurrency.AcrossAtomicLocal": (".ticket(", ANY),
    "concurrency.HandedToThreadBlocks": (".demo(", ANY),
}


def synchronizing_call(example: str, partition: str):
    path = SUITE / (f"{example}.allocsens.json" if partition.startswith("object") else f"{example}.json")
    if not path.exists():
        pytest.skip(f"{path} is missing: run graal-export/suite")
    facts, _ = load(path)
    suffix, expected = SYNCHRONIZING_CALLS[example]
    method = next(m for m in facts.methods if m.startswith(example) and suffix in m)
    return facts, method, expected


def check_suite_kill_sets_of_synchronization() -> None:
    """A call that synchronizes kills everything unless the lock or volatile field is only this
    thread's; the control, with the lock claimed to be another object, is narrowed, and so is the
    call to a method that locks an object a second thread is told about."""
    wrong = {}
    for example, (_, expected) in SYNCHRONIZING_CALLS.items():
        for partition in ("field", "object-field"):
            facts, method, _ = synchronizing_call(example, partition)
            answer = kills(facts, partition)[method]
            if (answer == ANY) != (expected == ANY) or (expected != ANY and partition == "field" and answer != expected):
                wrong[example, partition] = answer
    assert not wrong, wrong

    # Controls, which must change the answer: the monitor's object shared with another thread
    # makes the call kill everything, and a lock claimed to be an object nothing shares, as
    # a thread escape that misses a sharing path would claim, makes every other one narrow.
    facts, method, _ = synchronizing_call("concurrency.AcrossLocalMonitor", "field")
    tally = facts.methods[method]["locks"]["MonitorEnterNode at bci 0"][0]
    assert kills(replace(facts, shared=facts.shared | {tally}))[method] == ANY
    for example in ("concurrency.AcrossLockLocal", "concurrency.AcrossAcquireLocal", "concurrency.AcrossRelease"):
        facts, method, _ = synchronizing_call(example, "field")
        claimed = {site: ["claimed.OnlyHere"] for site in facts.methods[method]["locks"]}
        facts.methods[method]["locks"] = claimed
        assert kills(facts)[method] != ANY, example
    print("ok   suite: a call kills everything when it synchronizes on what another thread may reach, and only then")


def check_suite_blockers() -> None:
    """Why methods kill everything is told by what they reach: a lock on a shared object blocks, one on an
    object only this thread reaches only when all synchronization counts, and with none counting
    nothing blocks in these programs."""
    program = ["concurrency."]
    local, _ = load(SUITE / "concurrency.AcrossLocalMonitor.json")
    assert blockers(local, program, "shared") == {} and sum(blockers(local, program, "all").values()) == 3
    shared, _ = load(SUITE / "concurrency.AcrossLockSharedBlocks.json")
    assert sum(blockers(shared, program, "shared").values()) == 3 and blockers(shared, program, "none") == {}
    print("ok   suite: the blockers of a program's methods count synchronization as the kill sets do")


#: example → what the analysis says of the item where the program uses it, for the default analysis
#: and with allocation sites; None where the program's use is folded away. Each Published example
#: puts the item where another thread reaches it by a different way, and must be shared; each
#: control keeps it in something no one shares, and is local where the analysis can tell the
#: objects apart. LocalInLocalAtomic and LocalInLocalList are shared today: the code of AtomicReference.set,
#: ArrayList.add and the arrays under them is one for every object, so what it stores into the
#: shared one (an atomic reference and a list are shared) it stores into the local one. Variable handles
#: are natives to the standalone analysis, which shares what they are given.
PUBLICATION = {
    "PublishedByStatic": ("shared", "shared"),
    "PublishedByField": ("shared", "shared"),
    "PublishedByArray": ("shared", "shared"),
    "PublishedByArrayCopy": ("shared", "shared"),
    "PublishedByAtomic": ("shared", "shared"),
    "PublishedByQueue": (None, "shared"),
    "PublishedByMap": (None, "shared"),
    "PublishedByExecutor": (None, "shared"),
    "PublishedByVarHandle": (None, "shared"),
    "LocalInLocalObject": ("local", "local"),
    "LocalInLocalArray": ("local", "local"),
    "LocalInLocalQueue": (None, "local"),
    "LocalInLocalAtomic": ("shared", "shared"),
    "LocalInLocalList": ("shared", "shared"),
    "LocalInLocalVarHandle": (None, "shared"),
}


def check_suite_publication() -> None:
    """The item of each example is shared when and only when the example publishes it, as far as the
    analysis can tell; graal-export/publication-controls.sh leaves out each kind of site in turn,
    and each time the examples that kind publishes become local."""
    from effects.publication import item_shared
    from graal.graal_import import load_facts

    wrong = {}
    for example, expected in PUBLICATION.items():
        for variant, want in zip(("", ".allocsens"), expected):
            path = SUITE / f"concurrency.{example}{variant}.json"
            if not path.exists():
                pytest.skip(f"{path} is missing: run graal-export/suite")
            got = item_shared(load_facts(path), example)
            if want is not None and got != want:
                wrong[example, variant or ".default"] = got
    assert not wrong, wrong
    print("ok   suite: what another thread can reach is shared, through a static field, a field, an array, a copy, an atomic, a queue, a map and a task")


def check_suite_elidable_locks() -> None:
    """A monitor goes when every object it may lock is reached by one thread only and nothing waits on it;
    a lock on a shared object stays, and so does a local one that is waited on. Each answer has a control
    that changes it."""
    def facts(example: str) -> PointsToFacts:
        path = SUITE / f"concurrency.{example}.allocsens.json"
        if not path.exists():
            pytest.skip(f"{path} is missing: run graal-export/suite")
        return load_facts(path)

    def in_method(sites: dict[str, str], method: str) -> dict[str, str]:
        return {s: k for s, k in sites.items() if s.startswith(f"concurrency.{method}(")}

    # The tally of AcrossLocalMonitor is main's alone: its enter and its exit can go.
    local = facts("AcrossLocalMonitor")
    sites = in_method(elidable(local), "AcrossLocalMonitor$Tally.add")
    assert sorted(sites.values()).count("enter") == 1 and "exit" in sites.values(), sites
    # The control: if every object counted as shared, nothing could go.
    assert not elidable(replace(local, shared=None)), "a lock on a shared object stays"
    # A lock on a static object is every thread's.
    assert not in_method(elidable(facts("AcrossLockLocal")), "AcrossLockLocal.logged")
    # A local object that is waited on keeps its lock...
    waited = facts("WaitedOnKeepsLock")
    assert not in_method(elidable(waited), "WaitedOnKeepsLock.pass"), "a lock that wait needs stays"
    # ...and the control: without the waits in the facts the same lock is listed.
    unwaited = replace(waited, methods={m: {k: v for k, v in e.items() if k != "waits"} for m, e in waited.methods.items()})
    assert in_method(elidable(unwaited), "WaitedOnKeepsLock.pass"), "the lock would go if nothing waited on it"
    # A wait on an object the analysis can't name could be on any lock.
    unnamed = replace(local, methods={**local.methods, "concurrency.Elsewhere.wait()V": {"waits": {"wait at bci 0": None}}})
    assert not elidable(unnamed), "a wait on an unnamed object keeps every lock"
    print("ok   suite: the monitors that can go are those on objects one thread reaches that nothing waits on")


def check_suite_elidable_volatiles() -> None:
    """A volatile access of a field becomes an ordinary one when every object it may be on is reached by one
    thread only; on an object handed to a thread, or in a static field, it stays volatile."""
    def facts(example: str) -> PointsToFacts:
        path = SUITE / f"concurrency.{example}.allocsens.json"
        if not path.exists():
            pytest.skip(f"{path} is missing: run graal-export/suite")
        return load_facts(path)

    def in_method(sites: dict[str, str], method: str) -> dict[str, str]:
        return {s: k.split("\t")[0] for s, k in sites.items() if s.startswith(f"concurrency.{method}(")}

    local = facts("VolatileOnLocal")
    kinds = sorted(in_method(elidable(local), "VolatileOnLocal.fill").values())
    assert kinds == ["plain-read", "plain-read", "plain-write"], kinds
    # The control: if every object counted as shared, nothing could change.
    assert not elidable(replace(local, shared=None)), "a volatile access on a shared object stays"
    assert not in_method(elidable(facts("VolatileOnShared")), "VolatileOnShared.fill"), "the gauge a thread reaches stays volatile"
    assert not in_method(elidable(facts("AcrossAcquireLocal")), "AcrossAcquireLocal.poll"), "a static field is every thread's"
    print("ok   suite: the volatile accesses that become ordinary are those on objects one thread reaches")
