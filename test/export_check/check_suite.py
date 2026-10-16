"""Each example (graal-export/examples/) still shows what its comment says: the conversion examples by their shape, the optimization examples by
what the rules do under each partitioning, the controls by what they keep.

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
    """The volatile access, the lock and the switch are refused; the native call
    makes the method take every token."""
    for example, reason in (("limits.VolatileField", "volatile"), ("limits.Synchronized", "Monitor"),
                            ("limits.Switch", "IntegerSwitch")):
        program, translation = translate(example, "field")
        assert not program.structures and any(reason in why for why in translation.refused.values()), \
            (example, translation.refused)
    facts, graphs = load(SUITE / "limits.OpaqueCall.json")
    effects = analyse(facts, PARTITIONERS["field"](facts))
    s = demo(translate("limits.OpaqueCall", "field")[0])
    assert len(heaps(s.lambdas[0].params)) == len(effects.partitions)
    print("ok   suite: the limits are refused, and an opaque call takes every token")


#: example → partitioning → (loads forwarded, stores removed)
OPTIMIZED = {
    "forwarding.ForwardedByGraal": {"none": (0, 0), "field": (0, 0)},
    "forwarding.AcrossCall": {"none": (0, 0), "field": (1, 0)},
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
