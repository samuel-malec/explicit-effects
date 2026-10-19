"""Each example (graal-export/examples/) still shows what its comment says: the conversion examples by their shape, the optimization examples by
what the rules do under each partitioning, the controls by what they keep, and
the concurrency examples by what synchronization lets the rules do.

The exports come from `graal-export/suite` (or `make suite`); without them these
checks are skipped.
"""

from pathlib import Path

import pytest

from cthu import prelude
from cthu.ir import Program, Structure
from cthu.ssu import check
from effects.signatures import PARTITIONERS, analyse, no_analysis
from graal.graal_import import load
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
