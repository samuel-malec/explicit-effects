import subprocess
import sys
from pathlib import Path

from cthu import parser, prelude
from cthu.ir import Instr, Lambda, Program, Structure, function_type, to_text
from cthu.ssu import check
from effects.signatures import PARTITIONERS, analyse, no_analysis
from graal.graal_import import load
from graal2ct import shape
from graal2ct.shape import straighten
from graal2ct.translate import Translation

DATA = Path(__file__).resolve().parent.parent / "data"
EXAMPLES = DATA / "examples.json"
SIGNATURES = DATA / "signatures.json"
ALIASING = DATA / "aliasing.json"  # exported with allocation sites


def translate(path: Path, partition: str) -> Program:
    facts, graphs = load(path)
    effects = no_analysis() if partition == "none" else analyse(facts, PARTITIONERS[partition](facts))
    return Translation(graphs, effects).translate(sorted(graphs))


def structure(program: Program, name: str) -> Structure:
    return next(s for s in program.structures if s.name == name)


def cyclic(s: Structure) -> set[str]:
    """The λs that reach themselves through the λs they take."""
    refs = {lam.name: {i.op for i in lam.body if i.type == s.name} for lam in s.lambdas}
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


def origin(lam: Lambda, name: str) -> Instr:
    """The instruction that defines a value, past the dups linearize added."""
    defs = {out: i for i in lam.body for out in i.outs}
    while defs[name].op == "dup":
        name = defs[name].ins[0]
    return defs[name]


def check_shape() -> None:
    """The program takes a shape in which more of it is local. A branch whose arm throws on every path becomes a guard
    on each token, which leaves the method where that arm would have run: a null check's, and a call's on the
    exception it gave back. A block that only one jump reaches joins the λ that jumps: forwardAcrossWritingCall, a
    null check and three blocks split at its call, becomes one λ, with the guards of the null check on counter and
    then those of the call. A merge stays a λ (deadStoreBothArms' b5, which both arms jump to), and so does a loop
    header (hoistLoadOutOfLoop keeps a λ that reaches itself)."""
    program = translate(EXAMPLES, "field")
    writing = [lam.name for lam in structure(program, "Examples_forwardAcrossWritingCall").lambdas]
    straighten(program)
    s = structure(program, "Examples_forwardAcrossWritingCall")
    assert {"b1", "b2", "b3"} <= set(writing) and [lam.name for lam in s.lambdas] == ["run"], (writing, s.lambdas)
    guards = [i for i in s.lambdas[0].body if i.op == "guard"]
    assert len(guards) == 6 and all(g.exit == "throws" for g in guards), guards
    null = origin(s.lambdas[0], guards[0].ins[1])  # it leaves when counter is null, as the arm did
    assert null.op == "nil?" and null.ins[0].split("_")[0] == "p0", null
    thrown = origin(s.lambdas[0], guards[3].ins[1])  # it leaves when the call gave back an exception
    assert thrown.op == "not" and origin(s.lambdas[0], thrown.ins[0]).op == "nil?", thrown

    assert "b5" in {lam.name for lam in structure(program, "Examples_deadStoreBothArms").lambdas}
    assert cyclic(structure(program, "Examples_hoistLoadOutOfLoop"))
    print("ok   null checks and calls' exceptions become guards, and straight-line blocks one λ; merges and loop headers stay")


def check_straightened_programs_stay_valid() -> None:
    """After straightening, every program of the fixtures, under every partitioning, still passes the single-use and
    type checks, which include that a branch's frame is for arms of its type, and its text parses back. A second pass
    changes nothing."""
    graal = prelude.load()
    for path in (EXAMPLES, SIGNATURES, ALIASING):
        for partition in ("none", "field", "object", "object-field"):
            program = translate(path, partition)
            straighten(program)
            errors = check(program) + prelude.check(program, graal)
            assert not errors, (path.name, partition, errors[:5])
            module = parser.parse(to_text(program))
            assert list(module.structures) == [s.name for s in program.structures]
            text = to_text(program)
            straighten(program)
            assert to_text(program) == text, (path.name, partition)
    print("ok   straightened programs pass the single-use and type checks and parse back; a second pass changes nothing")


def check_merge_same_params() -> None:
    """When every caller of a λ passes the same value for two of its parameters, only the first is kept: the second
    is replaced by it where the body uses it. A caller that passes two different values keeps both. No example of
    the fixtures or of the suite has such a λ, so the pass is checked on small programs."""
    ftype = function_type(["int", "int"], ["int"])

    def program(first: str, second: str) -> tuple[Structure, Lambda]:
        entry = Lambda("run", [("x", "int"), ("z", "int")], [("r", "int")], [
            Instr("S", "m", [], ["k"], [ftype]),
            Instr(ftype, "call", ["k", first, second], ["r"], ["int"])])
        merged = Lambda("m", [("a", "int"), ("b", "int")], [("r", "int")], [Instr("int", "add", ["a", "b"], ["r"], ["int"])])
        return Structure("S", [entry, merged]), merged

    s, merged = program("x", "x")
    shape.merge_same_params(s)
    assert merged.body[0].ins == ["a", "a"], merged.body
    s, merged = program("x", "z")
    shape.merge_same_params(s)
    assert merged.body[0].ins == ["a", "b"], merged.body
    print("ok   a λ's two parameters that every caller gives the same value become one; different values stay two")


def check_the_flag() -> None:
    """`graal2ct --shape` prints the straightened program, and without it the translation as it is."""
    def run(*flags: str) -> str:
        done = subprocess.run([sys.executable, "-m", "graal2ct", str(EXAMPLES), "--partition", "field", *flags],
                              capture_output=True, text=True, check=True)
        assert done.stderr.strip().endswith("ok"), done.stderr[-200:]
        return done.stdout.rstrip("\n")

    program = translate(EXAMPLES, "field")
    plain = to_text(program).rstrip("\n")
    straighten(program)
    assert run("--shape") == to_text(program).rstrip("\n")
    assert run() == plain and plain != to_text(program).rstrip("\n")
    print("ok   --shape prints the straightened program, and the translation without it")


def check_the_checks_can_fail() -> None:
    """Without the step that turns branches to throwing arms into guards, or the one that joins blocks, `check_shape`
    fails; without the step that merges parameters, `check_merge_same_params` does."""
    for step, check_it in (("guard_exits", check_shape), ("fuse", check_shape), ("merge_same_params", check_merge_same_params)):
        kept = getattr(shape, step)
        setattr(shape, step, lambda *args: None)
        try:
            check_it()
        except AssertionError:
            continue
        else:
            raise AssertionError(f"{check_it.__name__} did not notice that {step} was gone")
        finally:
            setattr(shape, step, kept)
    print("ok   the checks fail when guard_exits, fuse or merge_same_params does nothing")
