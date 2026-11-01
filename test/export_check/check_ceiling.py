import json
import subprocess
import sys
import tempfile
from pathlib import Path

from diagnostics.ceiling import ceiling
from effects.kills import ANY, IGNORABLE, kills
from graal.graal_import import PointsToFacts

#: A small program with one method for each way a method can kill everything. `both` has two effects the facts
#: cannot name, so leaving one out frees nothing; `callsHash` and `callsPure` only call.
FACTS = PointsToFacts(
    methods={
        "P.pure()V": {},
        "P.hash()V": {"unknown": ["SubstrateIdentityHashCodeNode at P.hash()V:3"]},
        "P.clinit()V": {"unknown": ["EnsureClassInitializedNode at P.clinit()V:1"]},
        "P.lock()V": {"acquires": ["MonitorEnterNode at P.lock()V:0"]},
        "P.native()V": {"unknown": ["CFunctionPrologueNode at P.native()V:2"]},
        "P.both()V": {"unknown": ["SubstrateIdentityHashCodeNode at P.both()V:1", "CFunctionPrologueNode at P.both()V:4"]},
        "P.virtual()V": {"unresolved": ["call at P.virtual()V:5"]},
        "P.missing()V": {"callees": ["Q.nofacts()V"]},
        "P.callsHash()V": {"callees": ["P.hash()V"]},
        "P.callsPure()V": {"callees": ["P.pure()V"]},
    },
    fields={},
    shared=frozenset(),
)
ALL = set(FACTS.methods)


def opaque(*ignore: str) -> set[str]:
    return {m for m, w in kills(FACTS, "field", ignore).items() if w == ANY}


def check_nothing_is_ignored_by_default() -> None:
    """Without `ignore` every way of killing everything counts, and a method that only calls what is pure kills
    nothing."""
    assert opaque() == ALL - {"P.pure()V", "P.callsPure()V"}, opaque()
    assert kills(FACTS) == kills(FACTS, "field", ()) == kills(FACTS, "field", [])
    print("ok   no effect is ignored by default: each method that has one, or calls one, kills everything")


def check_each_effect_is_ignored_on_its_own() -> None:
    """Leaving an effect out frees the methods that have only that one, and the methods that call them; a method
    with another effect as well stays."""
    base = opaque()
    assert base - opaque("identity-hash") == {"P.hash()V", "P.callsHash()V"}
    assert base - opaque("class-initialization") == {"P.clinit()V"}
    assert base - opaque("synchronization") == {"P.lock()V"}
    assert base - opaque("unresolved-calls") == {"P.virtual()V"}
    assert base - opaque("calls-without-facts") == {"P.missing()V"}
    assert base - opaque("other-effects") == {"P.native()V"}
    assert "P.both()V" in opaque("identity-hash") and "P.both()V" in opaque("other-effects")  # every effect of a method counts, not the first
    assert "P.both()V" not in opaque("identity-hash", "other-effects")
    print("ok   each effect on its own frees only the methods that have it and the ones that call them; a method with two stays until both are left out")


def check_everything_ignored_frees_everything() -> None:
    assert opaque(*IGNORABLE) == set()
    rows = ceiling(FACTS, ["P."])
    assert rows[0][1:] == (len(ALL) - 2, len(ALL) - 2, len(ALL)), rows[0]
    assert rows[-1][1:] == (0, 0, len(ALL)) and rows[-1][0].endswith("= everything"), rows[-1]
    chain = [r[1] for r in rows if r[0] == "the three layers" or r[0].startswith("+ ")]
    assert chain == sorted(chain, reverse=True), chain  # adding an effect to the ones left out never makes a method opaque
    print("ok   leaving out everything frees every method; adding an effect to the ones left out never adds an opaque method")


def check_the_command_line() -> None:
    """`--ignore all` is every effect; a name that is not one is refused; the answer says it is not sound."""
    with tempfile.TemporaryDirectory() as tmp:
        export, out = Path(tmp) / "export.json", Path(tmp) / "kills.txt"
        export.write_text(json.dumps({"methods": FACTS.methods, "fields": {}}))

        def run(*flags: str) -> subprocess.CompletedProcess:
            return subprocess.run([sys.executable, "-m", "effects.kills", str(export), "-o", str(out), *flags], capture_output=True, text=True)

        done = run("--ignore", "all")
        assert done.returncode == 0 and "upper bound, not sound" in done.stderr, done.stderr
        assert all(line.split("\t")[1] != ANY for line in out.read_text().splitlines())
        done = run()
        assert done.returncode == 0 and "not sound" not in done.stderr and ANY in out.read_text()
        done = run("--ignore", "identity-hash,bogus")
        assert done.returncode == 2 and "bogus" in done.stderr, done.stderr
    try:
        kills(FACTS, "field", ["bogus"])
    except ValueError:
        pass
    else:
        raise AssertionError("an effect that cannot be ignored was accepted")
    print("ok   --ignore all leaves nothing opaque and says the sets are not sound; an unknown effect is refused")


def check_the_checks_can_fail() -> None:
    """If only the first of a method's effects were looked at, leaving the hash out would free `both`; the check
    of each effect on its own notices."""
    import effects.kills as module

    original = module.blocks

    def first_only(facts, method, ignore=()):
        return original(facts, {**method, "unknown": list(method.get("unknown", ()))[:1]}, ignore)

    module.blocks = first_only
    try:
        check_each_effect_is_ignored_on_its_own()
    except AssertionError:
        pass
    else:
        raise AssertionError("the check did not notice that only the first effect of a method was read")
    finally:
        module.blocks = original
    print("ok   the check of each effect fails when only a method's first effect is read")
