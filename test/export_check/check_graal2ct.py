import copy
import dataclasses
import re
from pathlib import Path

from cthu import parser, prelude
from cthu.ir import Instr, Program, to_text
from cthu.lexer import ParseError
from cthu.ssu import LinearityError, check, linearize
from cthu.ir import Lambda
from effects.signatures import PARTITIONERS, REST, analyse, by_field, no_analysis, one_heap
from graal.graal_import import load
from graal2ct.translate import Translation

DATA = Path(__file__).resolve().parent / "data"
EXAMPLES = DATA / "examples.json"


def translate(partition: str = "none") -> tuple[Program, Translation]:
    facts, graphs = load(EXAMPLES)
    effects = no_analysis() if partition == "none" else analyse(facts, PARTITIONERS[partition])
    translation = Translation(graphs, effects)
    return translation.translate(sorted(graphs)), translation


def structure(program: Program, name: str):
    return next(s for s in program.structures if s.name == name)


def lam(program: Program, structure_name: str, name: str) -> Lambda:
    return next(l for l in structure(program, structure_name).lambdas if l.name == name)


def ops(lam: Lambda) -> list[str]:
    return [f"{i.type} {i.op}" for i in lam.body]


def check_examples_translate() -> None:
    """Every method of Examples translates and passes the static-single-use
    check, except main, which allocates, and forwardAcrossVirtualCall, whose
    interface call has two targets."""
    program, translation = translate()
    expected = {"Examples.main": "allocation", "Examples.forwardAcrossVirtualCall": "with 2 targets"}
    assert translation.refused.keys() == expected.keys(), translation.refused
    for key, reason in expected.items():
        assert reason in translation.refused[key], translation.refused[key]
    errors = check(program)
    assert not errors, errors[:5]
    print("ok   Examples translates, every λ passes the static-single-use check; main and the two-target call are refused")


def check_heap_is_threaded() -> None:
    """Each memory operation consumes the current heap and produces the next:
    the three stores of deadStoreOtherField are ordered by h → h1 → h2 → h3."""
    program, _ = translate()
    body = lam(program, "Examples_deadStoreOtherField", "b2").body
    stores = [i for i in body if i.type == "heap" and i.op.startswith("set_")]
    assert [s.ins[0] for s in stores] == ["h", "h1", "h2"] and [s.outs[0] for s in stores] == ["h1", "h2", "h3"], stores
    print("ok   the heap token threads through memory operations in order")


def check_branches_fork_the_heap() -> None:
    """An If picks one of two λs with opt/join; its frame hands the heap to
    both with `fork` -- exactly one runs -- while plain values are dup'ed."""
    program, _ = translate()
    run = ops(lam(program, "Examples_deadStoreBothArms", "run"))
    assert "bool not" in run, run
    assert sum(op.endswith(" opt") for op in run) == 2 and sum(op.endswith(" join") for op in run) == 1, run
    frame = ops(lam(program, "Examples_deadStoreBothArms", "frame_0"))
    assert "heap fork" in frame and "heap dup" not in frame, frame
    print("ok   a branch is opt/join over two λs; its frame forks the heap")


def recursive_lambdas(program: Program, structure_name: str) -> set[str]:
    """The λs that can reach themselves through the λs they reference."""
    s = structure(program, structure_name)
    calls = {l.name: {i.op for i in l.body if i.type == s.name} for l in s.lambdas}
    recursive = set()
    for start in calls:
        seen, work = set(), list(calls[start])
        while work:
            name = work.pop()
            if name == start:
                recursive.add(start)
                break
            if name not in seen:
                seen.add(name)
                work.extend(calls.get(name, ()))
    return recursive


def check_loops_are_recursion() -> None:
    """hoistLoadOutOfLoop has a loop, so some λ reaches itself: the header,
    called again from the back edge. deadStoreBothArms has none, so no λ does."""
    program, _ = translate()
    loop = recursive_lambdas(program, "Examples_hoistLoadOutOfLoop")
    assert loop, "no λ in hoistLoadOutOfLoop calls itself"
    assert not recursive_lambdas(program, "Examples_deadStoreBothArms")
    print(f"ok   a loop is recursion ({', '.join(sorted(loop))} in hoistLoadOutOfLoop); a loop-free method has none")


def check_exceptions_trap() -> None:
    """For now a path that throws is a trap that consumes the heap, and a
    call's exception edge is not followed."""
    program, _ = translate()
    reset = structure(program, "Examples_deadStoreOtherField")
    traps = [l.name for l in reset.lambdas if "heap trap" in ops(l)]
    assert traps, [l.name for l in reset.lambdas]
    assert all(ops(lam(program, reset.name, t))[-2:] == ["heap trap", "heap bot"] for t in traps)
    assert not any(i.op == "ExceptionObject" for l in reset.lambdas for i in l.body)
    print("ok   a throwing path is a trap; call exception edges are not followed")


def check_caught_exceptions_are_refused() -> None:
    """Exceptions trap, so no handler ever runs: a method whose handler could
    complete normally is refused, not translated without it. Every exception
    edge in Examples leads to a rethrow, so length translates; once the
    handler of its recursive call returns instead, length is refused."""
    _, graphs = load(EXAMPLES)
    key = "Examples.length"
    graph = graphs[key]
    handler = next(e.to for b in graph.blocks.values() for e in b.succs if e.label == "exception")
    translation = Translation(graphs)
    translation.translate([key])
    assert key not in translation.refused and graph.blocks[handler].exit == "unwind", translation.refused

    returning = dataclasses.replace(graph.blocks[handler], exit="return")
    caught = {**graphs, key: dataclasses.replace(graph, blocks={**graph.blocks, handler: returning})}
    translation = Translation(caught)
    translation.translate([key])
    assert "exception handler" in translation.refused.get(key, ""), translation.refused
    print(f"ok   a handler that can complete normally is refused ({translation.refused[key]}); one that rethrows traps")


def check_what_the_export_flags_is_refused() -> None:
    """A method the export flags, for something it could not express such as
    a volatile access, is refused with the export's reason, although each of
    its nodes would translate: a volatile store looks like any other. No
    method of Examples is flagged."""
    _, graphs = load(EXAMPLES)
    assert not any(g.unsupported for g in graphs.values()), {k: g.unsupported for k, g in graphs.items() if g.unsupported}
    key = "Examples.deadStoreOtherField"
    reason = "ordered (volatile) access to Examples$Counter.value at bci 2"
    flagged = {**graphs, key: dataclasses.replace(graphs[key], unsupported=(reason,))}
    translation = Translation(flagged)
    translation.translate([key])
    assert translation.refused == {key: reason}, translation.refused
    print("ok   a method the export flags (a volatile access) is refused with its reason; Examples has none")


def method_calls(program: Program) -> list[tuple[str, str, str]]:
    """(caller, callee structure, closure type) for every call to a method."""
    calls = []
    for s in program.structures:
        for l in s.lambdas:
            callee = {i.outs[0]: i.type for i in l.body if i.op == "run"}
            calls += [(s.name, callee[i.ins[0]], i.type) for i in l.body if i.op == "call" and i.ins[0] in callee]
    return calls


def run_types(program: Program) -> dict[str, str]:
    """Each structure's entry type: what a call to that method must have."""
    return {s.name: lam(program, s.name, "run").function_type for s in program.structures}


def check_overloads_resolve() -> None:
    """A call names its callee by name and descriptor, so the two countInto
    overloads stay apart: forwardAcrossWritingCall calls the one for a Logger,
    forwardAcrossCallControl the one for a Counter. Every call to a translated
    method has the type of that method's run, and calls outside the export
    keep their overloads apart too."""
    program, translation = translate()
    run = run_types(program)
    calls = method_calls(program)
    assert all(run[callee] == t for _, callee, t in calls if callee in run), calls

    callee = {caller: c for caller, c, _ in calls if "countInto" in c}
    writing, control = callee["Examples_forwardAcrossWritingCall"], callee["Examples_forwardAcrossCallControl"]
    assert "Logger" in writing and "Counter" in control and writing in run and control in run, (writing, control)
    assert translation.callee_structure("java.io.PrintStream.println(I)V") != \
        translation.callee_structure("java.io.PrintStream.println(J)V")
    print(f"ok   overloads resolve by descriptor: {writing} and {control} stay apart")


def check_partial_translation() -> None:
    """Translating some methods only, a call to one left out names a structure
    the program lists as external, so it still type-checks. Without that
    entry, the call names a structure nobody defines."""
    _, graphs = load(EXAMPLES)
    program = Translation(graphs).translate(["Examples.forwardAcrossWritingCall"])
    count_logger = "Examples_countInto_LExamples_Logger_LExamples_Link__V"
    assert count_logger in program.externals, program.externals
    graal = prelude.load()
    assert not prelude.check(program, graal)
    del program.externals[count_logger]
    assert any("no structure" in e for e in prelude.check(program, graal))
    print("ok   a call to a method left out of the translation is external, and type-checks")


def check_programs_type_check() -> None:
    """graal.ct is a consistent prelude, and every instruction of Examples
    applies an operation it declares to values of the types it takes. Broken
    preludes are caught, and reported first by check: an unbound operation, a
    missing parent signature, a cycle of signatures, a wrong number of
    arguments to a signature. So are a copied heap and a mistyped value."""
    graal = prelude.load()
    assert not graal.errors, graal.errors
    program, _ = translate()
    errors = prelude.check(program, graal)
    assert not errors, errors[:5]

    for old, new, expected in (
            ("    ult? = graal_int_ult\n", "", "structure int does not bind ult?"),
            (": lattice[ T, B ]", ": latice[ T, B ]", "signature linear: no signature latice"),
            ("signature lattice[ T, B ]\n", "signature lattice[ T, B ] : simple[ T, T, B ]\n",
             "signature lattice extends itself"),
            (": lattice[ T, B ]", ": lattice[ T, S, B ]", "signature linear: lattice[ T, B ] takes 2 argument(s), given 3"),
            ("structure int : arithmetic[ int, stck, bool ]", "structure int : arithmetic[ int, stck ]",
             "structure int: arithmetic[ T, S, B ] takes 3 argument(s), given 2"),
            ("signature function[ F, S, B, I, O, G ]", "signature function[ F, S, B, I, O ]",
             "function types: function[ F, S, B, I, O ] takes 5 argument(s), given 6")):
        text = prelude.GRAAL.read_text()
        assert old in text, old
        broken = prelude.parse(text.replace(old, new, 1))
        assert any(e.startswith(expected) for e in broken.errors), (expected, broken.errors)
        assert prelude.check(program, broken)[:len(broken.errors)] == [f"prelude: {e}" for e in broken.errors]

    b2 = lam(program, "Examples_deadStoreOtherField", "b2")
    b2.body.insert(0, Instr("heap", "dup", ["h"], ["hx", "hy"], ["heap", "heap"]))
    constant = next(i for i in b2.body if i.op.startswith("cons_"))
    constant.out_types = ["long"]
    errors = prelude.check(program, graal)
    assert any("heap has no dup" in e for e in errors), errors
    assert any(constant.text() in e and "given" in e for e in errors), errors
    print("ok   every instruction type-checks against graal.ct; a broken prelude, a copied heap and a mistyped value don't")


def check_signatures() -> None:
    """A signature is a method's own field accesses and its callees', to a
    fixpoint: countInto for a Logger touches Link.next and Logger.count, so
    forwardAcrossWritingCall, which calls it, gets those and its own
    Counter.value, and the recursive length only reads Link.next. The facts
    cover the platform too, so a constructor, which calls Object.<init>,
    touches nothing; without Object.<init>'s facts it would be opaque and get
    every partition, the rest of memory included. The platform's fields belong
    to the rest of memory: main reads System.out, which gets no partition. With
    one heap, forwardAcrossWritingCall gets just that."""
    facts, _ = load(EXAMPLES)
    effects = analyse(facts, by_field)
    e = "Examples"
    count_logger = f"{e}.countInto(L{e}$Logger;L{e}$Link;)V"
    assert effects.tokens(count_logger) == (f"{e}$Link.next", f"{e}$Logger.count"), effects.tokens(count_logger)
    writing = f"{e}.forwardAcrossWritingCall(L{e}$Counter;L{e}$Logger;L{e}$Link;)I"
    assert effects.tokens(writing) == (f"{e}$Counter.value", f"{e}$Link.next", f"{e}$Logger.count"), effects.tokens(writing)
    length = effects.signatures[f"{e}.length(L{e}$Link;)I"]
    assert length.reads == {f"{e}$Link.next"} and not length.writes and not length.opaque, length

    init = f"{e}$Counter.<init>()V"
    assert effects.tokens(init) == () and not effects.signatures[init].opaque, effects.signatures[init]
    blind = copy.deepcopy(facts)
    del blind.methods["java.lang.Object.<init>()V"]
    unknown = analyse(blind, by_field)
    assert unknown.signatures[init].opaque and unknown.tokens(init) == unknown.partitions and REST in unknown.partitions

    main = f"{e}.main([Ljava/lang/String;)V"
    assert "java.lang.System.out" in facts.methods[main]["reads"]
    assert all(p == REST or p.startswith(f"{e}$") for p in effects.partitions), effects.partitions
    assert analyse(facts, one_heap).tokens(writing) == ("heap",)
    print("ok   signatures: a caller gets its callee's partitions, length only reads, a constructor touches nothing,"
          " platform fields are the rest of memory")


def check_facts_cover_every_kind_of_field() -> None:
    """The facts list field accesses of every kind. The analysis builds no flow
    for a float or a double, so those come from the graphs: Double.<init>
    writes Double.value and Double.doubleValue reads it, as Long.<init> writes
    Long.value. Double.valueOf, which calls the constructor, touches the rest of
    memory, where the platform's fields go; without that write it would touch
    nothing."""
    facts, _ = load(EXAMPLES)
    methods = facts.methods
    assert methods["java.lang.Double.<init>(D)V"]["writes"] == ["java.lang.Double.value"], methods["java.lang.Double.<init>(D)V"]
    assert methods["java.lang.Double.doubleValue()D"]["reads"] == ["java.lang.Double.value"]
    assert methods["java.lang.Float.<init>(F)V"]["writes"] == ["java.lang.Float.value"]
    assert methods["java.lang.Long.<init>(J)V"]["writes"] == ["java.lang.Long.value"]

    value_of = "java.lang.Double.valueOf(D)Ljava/lang/Double;"
    assert analyse(facts, by_field).tokens(value_of) == (REST,), analyse(facts, by_field).tokens(value_of)
    blind = copy.deepcopy(facts)
    blind.methods["java.lang.Double.<init>(D)V"]["writes"] = []
    assert analyse(blind, by_field).tokens(value_of) == ()
    print("ok   facts cover float and double fields: Double.valueOf touches the rest of memory through Double.<init>")


def check_partitions_separate_effects() -> None:
    """With a token per field, the call in forwardAcrossWritingCall takes only
    the Link.next and Logger.count tokens, so the Counter.value token goes from
    the store to the load without passing the call. Every partitioning
    translates the same methods, and passes the single-use and type checks.
    Without an analysis the call takes the one heap token."""
    graal = prelude.load()
    _, baseline = translate()
    for partition in PARTITIONERS:
        program, translation = translate(partition)
        assert translation.refused.keys() == baseline.refused.keys(), (partition, translation.refused)
        errors = check(program) + prelude.check(program, graal)
        assert not errors, (partition, errors[:5])

    def writing_call(partition: str) -> tuple[list[str], str, list[str]]:
        """The tokens the call takes, the token the store gives, and what the jump to the load passes."""
        program, _ = translate(partition)
        b2 = lam(program, "Examples_forwardAcrossWritingCall", "b2")
        call = next(i for i in b2.body if i.op == "call" and "countInto" in i.note)
        store = next(i for i in b2.body if i.op.startswith("set_"))
        tokens = [re.sub(r"\d+$", "", name) for name in call.ins if name.startswith("h")]
        return tokens, store.outs[0], b2.body[-1].ins

    tokens, stored, passed_on = writing_call("field")
    assert tokens == ["h_next", "h_count"] and stored in passed_on, (tokens, stored, passed_on)
    tokens, _, _ = writing_call("none")
    assert tokens == ["h"], tokens
    print("ok   per field, the writing call takes h_next and h_count, and h_value goes from the store to the load")


def check_the_parser_reads_the_output_back() -> None:
    """Printing a translated program and parsing it back gives the same
    declarations, structures, λs and instructions. A broken line of the
    prelude is reported where it is."""
    for partition in ("none", "field"):
        program, _ = translate(partition)
        module = parser.parse(to_text(program))
        assert list(module.fields.items()) == list(program.fields.items()) and module.classes == program.classes
        assert list(module.structures) == [s.name for s in program.structures]
        for s in program.structures:
            parsed = module.structures[s.name].lambdas
            assert list(parsed) == [l.name for l in s.lambdas], s.name
            for l in s.lambdas:
                p = parsed[l.name]
                assert (p.params, p.outs) == ([n for n, _ in l.params], [n for n, _ in l.outs]), (s.name, l.name)
                assert [(i.structure, i.op, i.ins, i.outs) for i in p.body] == \
                    [(i.type, i.op, i.ins, i.outs) for i in l.body], (s.name, l.name)

    lines = prelude.GRAAL.read_text().splitlines()
    broken = next(n for n, line in enumerate(lines) if "∷" in line and "→" in line)
    lines[broken] = lines[broken].replace("→", "")
    try:
        parser.parse("\n".join(lines))
    except ParseError as e:
        assert e.line == broken + 1, (str(e), broken + 1)
        print(f"ok   graal2ct's output parses back unchanged; a line missing its arrow is reported at graal.ct:{e}")
        return
    raise AssertionError("a line missing its arrow parsed")


def check_the_checker_can_fail() -> None:
    """Break a translated λ three ways; the checker must notice each, and
    linearize must refuse to copy the heap."""
    program, _ = translate()

    def broken(edit) -> list[str]:
        p = copy.deepcopy(program)
        target = lam(p, "Examples_deadStoreOtherField", "b2")
        edit(target)
        return check(p)

    def drop_a_drop(l):  # a value now never used
        l.body.append(Instr("int", "cons_7", [], ["unused"], ["int"]))

    def use_twice(l):  # p0's second use without a dup
        l.body = [i for i in l.body if not (i.op == "dup" and i.ins == ["p0"])]
        for i in l.body:
            i.ins = ["p0" if n.startswith("p0_") else n for n in i.ins]

    def copy_heap(l):
        l.body.insert(0, Instr("heap", "dup", ["h"], ["hx", "hy"], ["heap", "heap"]))

    for edit, expected in ((drop_a_drop, r"used 0 times"), (use_twice, r"p0 used [2-9] times"), (copy_heap, r"dup of linear")):
        errors = broken(edit)
        assert any(re.search(expected, e) for e in errors), (edit.__name__, errors)
    assert not check(program), "the unbroken program must still pass"

    l = Lambda("t", [("h", "heap")], [("hout", "heap")],
               [Instr("heap", "trap", ["h"]), Instr("heap", "move", ["h"], ["hout"], ["heap"])])
    try:
        linearize(l)
    except LinearityError:
        print("ok   the checker catches an unused value, a double use and a copied heap; linearize won't copy the heap")
        return
    raise AssertionError("linearize copied the heap")


if __name__ == "__main__":
    check_examples_translate()
    check_heap_is_threaded()
    check_branches_fork_the_heap()
    check_loops_are_recursion()
    check_exceptions_trap()
    check_caught_exceptions_are_refused()
    check_what_the_export_flags_is_refused()
    check_overloads_resolve()
    check_partial_translation()
    check_programs_type_check()
    check_signatures()
    check_facts_cover_every_kind_of_field()
    check_partitions_separate_effects()
    check_the_parser_reads_the_output_back()
    check_the_checker_can_fail()
    print("all checks passed")
