import effects.kills
from diagnostics.blockers import nearest_through
from diagnostics.ceiling import LAYERS, ceiling
from diagnostics.unresolved import entries, part, target_kind
from effects.kills import ANY, IGNORABLE, kills, opaque
from graal.graal_import import PointsToFacts

#: A program (`app.`) that calls the platform (`java.`): `run` becomes opaque through two roots, the lock in `fillInStackTrace`
#: behind `Throwable.<init>` and the identity hash of `Object.equals` behind `helper`; `ffi` and `virtual` have an unresolved call of
#: their own; `pure` and `callsPure` kill nothing.
FACTS = PointsToFacts(
    methods={
        "app.Main.run()V": {"callees": ["java.lang.Throwable.<init>(Ljava/lang/String;)V", "app.Main.helper()V"]},
        "app.Main.helper()V": {"callees": ["java.lang.Object.equals(Ljava/lang/Object;)Z"]},
        "app.Main.ffi()V": {"unresolved": ["<indirect> at bci 3 (no flow)"]},
        "app.Main.virtual()V": {"unresolved": ["java.util.Foo.bar()V at bci 5 (no callees)", "scala.Bar.baz()V at bci 9 (disabled)"]},
        "app.Main.pure()V": {},
        "app.Main.callsPure()V": {"callees": ["app.Main.pure()V"]},
        "java.lang.Throwable.<init>(Ljava/lang/String;)V": {"callees": ["java.lang.Throwable.fillInStackTrace(I)Ljava/lang/Throwable;"]},
        "java.lang.Throwable.fillInStackTrace(I)Ljava/lang/Throwable;": {"acquires": ["MonitorEnterNode at java.lang.Throwable.fillInStackTrace(I)Ljava/lang/Throwable;:0"]},
        "java.lang.Object.equals(Ljava/lang/Object;)Z": {"unknown": ["SubstrateIdentityHashCodeNode at java.lang.Object.equals(Ljava/lang/Object;)Z:2"]},
    },
    fields={},
    shared=frozenset(),
)


def check_opaque_is_the_methods_that_kill_everything() -> None:
    """`opaque` names exactly the methods `kills` gives `any`, whatever is left out, without working out a set."""
    for ignore in [(), *[(name,) for name in IGNORABLE], LAYERS, tuple(IGNORABLE)]:
        killing = {m for m, w in kills(FACTS, "field", ignore).items() if w == ANY}
        assert set(opaque(FACTS, ignore)) == killing, ignore
    assert set(opaque(FACTS)) == {m for m in FACTS.methods if m not in ("app.Main.pure()V", "app.Main.callsPure()V")}
    assert opaque(FACTS, tuple(IGNORABLE)) == {}
    try:
        opaque(FACTS, ["bogus"])
    except ValueError:
        pass
    else:
        raise AssertionError("an effect that cannot be ignored was accepted")
    print("ok   opaque() names the methods kills() gives any, for each effect left out, the three layers and all of them")


def check_the_ceiling_counts_with_opaque() -> None:
    rows = ceiling(FACTS, [])
    assert rows[0][1:] == (4, 7, 6) and rows[-1][1:] == (0, 0, 6), rows
    assert next(r for r in rows if r[0] == "identity-hash")[1:] == (3, 5, 6)  # helper stops being opaque, run still is through the lock
    print("ok   the ceiling's rows come from opaque()")


def check_gateways_and_roots() -> None:
    """Each program method counts under the roots and the first platform methods nearest to it; ties count under each."""
    program, gateways, roots = nearest_through(FACTS, [])
    assert program == 4, program  # run, helper, ffi, virtual
    gate = {m: (direct, first) for m, direct, first, _ in gateways}
    assert gate == {"java.lang.Throwable.<init>(Ljava/lang/String;)V": (1, 1), "java.lang.Object.equals(Ljava/lang/Object;)Z": (1, 2)}, gate
    root = {m: first for m, _, first, _ in roots}
    assert root == {"java.lang.Throwable.fillInStackTrace(I)Ljava/lang/Throwable;": 1, "java.lang.Object.equals(Ljava/lang/Object;)Z": 2,
                    "app.Main.ffi()V": 1, "app.Main.virtual()V": 1}, root
    print("ok   the gateways and roots are the nearest ones: run ties between the lock behind Throwable.<init> and the hash behind equals")


def check_unresolved_calls_are_sorted() -> None:
    found = entries(FACTS, list(FACTS.methods))
    assert sorted((t, why) for _, t, _, why in found) == [("<indirect>", "no flow"), ("java.util.Foo.bar()V", "no callees"), ("scala.Bar.baz()V", "disabled")], found
    assert target_kind("<indirect>").startswith("no target method")
    assert target_kind("java.util.Foo.bar()V") == "method, JDK"
    assert target_kind("scala.Bar.baz()V") == "method, Scala library"
    assert target_kind("java.lang.Object.<init>()V") == "constructor, JDK"
    assert target_kind("java.lang.invoke.MethodHandle.invokeBasic()V") == "method handle or reflective invoke"
    assert part("com.oracle.svm.core.jni.JNIJavaCallWrapperHolder.x()V") == "VM and compiler" and part("app.Main.run()V") == "program"
    assert part("java.lang.reflect.Method.invoke(Ljava/lang/Object;)V") == "JDK: reflection"
    print("ok   unresolved calls are read as target, bci and reason, and sorted by what they call and where they are")


def check_the_checks_can_fail() -> None:
    """If a method that has a cause were not a root, the lock behind `Throwable.<init>` would go missing."""
    original = effects.kills.blocks

    def ignores_locks(facts, method, ignore=()):
        return original(facts, {**method, "acquires": []}, ignore)

    effects.kills.blocks = ignores_locks
    try:
        check_opaque_is_the_methods_that_kill_everything()
    except AssertionError:
        pass
    else:
        raise AssertionError("the check did not notice that synchronization was not read")
    finally:
        effects.kills.blocks = original
    print("ok   the check fails when a kind of effect is not read")
