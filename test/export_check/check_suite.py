"""Each example (graal-export/examples/) still shows what its comment says: the conversion examples by their shape, the optimization examples by
what the rules do under each partitioning, the controls by what they keep, and
the concurrency examples by what synchronization lets the rules do.

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
from rules import memory
from rules.compare import looping

SUITE = Path(__file__).parents[2] / "graal-export" / "out" / "suite"


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


#: example → partitioning → (loads forwarded, stores removed)
OPTIMIZED = {
    "forwarding.ForwardedByGraal": {"none": (0, 0), "field": (0, 0)},
    "forwarding.AcrossCall": {"none": (0, 0), "field": (1, 0)},
    "forwarding.AcrossReadingCall": {"none": (0, 0), "field": (1, 0)},
    "forwarding.WritingCallBlocks": {"none": (0, 0), "field": (0, 0)},
    "forwarding.RepeatedLoad": {"none": (0, 0), "field": (1, 0)},
    "forwarding.IntoBranchArm": {"none": (0, 0), "field": (1, 0)},
    "forwarding.AcrossMerge": {"none": (1, 0), "field": (1, 0)},
    "forwarding.IntoLoop": {"none": (0, 0), "field": (1, 0)},
    "forwarding.LoopCarried": {"none": (0, 0), "field": (1, 0)},
    "forwarding.OutOfLoop": {"none": (0, 0), "field": (1, 0)},
    "forwarding.WritingCallInLoopBlocks": {"none": (0, 0), "field": (0, 0)},
    "deadstores.Adjacent": {"none": (0, 1), "field": (0, 1)},
    "deadstores.OtherFieldBetween": {"none": (0, 0), "field": (0, 1)},
    "deadstores.BothArms": {"none": (0, 1), "field": (0, 1)},
    "deadstores.OneArmKeeps": {"none": (0, 0), "field": (0, 0)},
    "deadstores.CallBetweenKeeps": {"none": (0, 0), "field": (0, 0)},
    "deadstores.ReadThroughAliasKeeps": {"none": (0, 0), "field": (0, 0)},
    "objects.ForwardPastOtherObject": {"field": (0, 0), "object-field": (1, 0)},
    "objects.ForwardPastMaybeAlias": {"field": (0, 0), "object-field": (0, 0)},
    "objects.CallOnOtherObject": {"field": (0, 0), "object-field": (1, 0)},
    "objects.DeadStorePastOtherObject": {"field": (0, 0), "object-field": (0, 1)},
    "objects.DeadStoreMaybeAlias": {"field": (0, 0), "object-field": (0, 0)},
}


def check_suite_optimizations() -> None:
    """Each optimization example forwards and removes what its comment says under
    each partitioning, and each control nothing."""
    wrong = {}
    for example, expected in OPTIMIZED.items():
        for partition, (forwarded, removed) in expected.items():
            program, _ = translate(example, partition)
            done = memory.apply(program)
            assert not check(program) + prelude.check(program, prelude.load()), (example, partition)
            if (len(done.forwarded), len(done.removed)) != (forwarded, removed):
                wrong[example, partition] = (done.forwarded, done.removed)
    assert not wrong, wrong
    print("ok   suite: each optimization example is rewritten as its comment says, and no control is")


#: example → whether the Java memory model lets the load take the value the method already has,
#: or the first store go, in a program free of data races → (loads forwarded, stores removed) today, per field and per
#: object and field. RacySpin races, and the model promises it nothing, so the rules may hoist
#: its load. An acquire writes, and a release reads, the partitions another thread may touch;
#: memory only this thread reaches, and a lock on an object only it reaches, play no part.
#: AcrossAtomicLocal keeps its load: its helper reaches code without facts, so the counter it is
#: given counts as shared. The controls must never be rewritten.
SYNCHRONIZING = {
    "concurrency.AcrossRelease": (True, (1, 0)),
    "concurrency.AcrossAcquireLocal": (True, (1, 0)),
    "concurrency.AcrossAcquireSharedBlocks": (False, (0, 0)),
    "concurrency.AcrossLockLocal": (True, (1, 0)),
    "concurrency.AcrossLockSharedBlocks": (False, (0, 0)),
    "concurrency.AcrossLocalMonitor": (True, (1, 0)),
    "concurrency.AcrossAtomicLocal": (True, (0, 0)),
    "concurrency.FinalAcrossLock": (True, (1, 0)),
    "concurrency.HandedToThreadBlocks": (False, (0, 0)),
    "concurrency.RacySpin": (True, (0, 0)),
    "concurrency.ReleaseInMethod": (True, (1, 0)),
    "concurrency.AcquireInMethodBlocks": (False, (0, 0)),
    "concurrency.DeadStoreAcrossReleaseKeeps": (False, (0, 0)),
    "concurrency.DeadStoreAcrossAcquire": (True, (0, 1)),
}


def check_suite_concurrency() -> None:
    """No load is forwarded where another thread's write may become visible in between, no
    store is removed that another thread may read, and each concurrency example is rewritten
    as its comment says."""
    wrong = {}
    for example, (allowed, expected) in SYNCHRONIZING.items():
        for partition in ("field", "object-field"):
            program, _ = translate(example, partition)
            demo(program)  # translated: a refused method would keep its loads for the wrong reason
            done = memory.apply(program)
            assert not check(program) + prelude.check(program, prelude.load()), (example, partition)
            assert allowed or not (done.forwarded or done.removed), (example, partition, done.forwarded, done.removed)
            if (len(done.forwarded), len(done.removed)) != expected:
                wrong[example, partition] = (done.forwarded, done.removed)
    assert not wrong, wrong
    print("ok   suite: no load is forwarded across synchronization that may let another thread's write in")


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
