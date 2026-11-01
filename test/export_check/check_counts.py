import importlib.util
import tempfile
from pathlib import Path

# scripts/evaluation/counts.py is a script, not a package
_spec = importlib.util.spec_from_file_location("counts", Path(__file__).resolve().parents[2] / "scripts" / "evaluation" / "counts.py")
counts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(counts)

#: Three methods as a build's counts.txt lists them: a loop access is listed once, under `field(loop)`; a lambda's name has
#: `$$Lambda/0x…` in it and no parameter types; a call's detail line is indented deeper than the row.
TEXT = """\
A.run(int)
    kills      calls 2   writes A.count A.count(loop)×2 reads A.count×3 A.count(loop) B.next(loop)×4
        A.helper() kills nothing
A$$Lambda/0xc6a3883ad1d74211d0ce6db95917a9520.apply(Object)
    kills      calls 0   writes B.mark                    reads Lambda/0xc6a3883ad1d74211d0ce6db95917a9520.arg$1
B.empty()
    kills      calls 1   writes -                        reads -
"""


def check_a_loop_access_is_counted_once() -> None:
    """An access in a loop is listed under `field(loop)` alone, so it is one load, not two."""
    methods = _read(TEXT)
    run = methods["A.run(int)"]
    assert (run.loads, run.loop_loads) == (3 + 1 + 4, 1 + 4), run
    assert (run.stores, run.loop_stores) == (1 + 2, 2), run
    assert run.calls == 2
    print("ok   an access in a loop is one load, listed once")


def check_a_lambda_is_a_method_of_its_own() -> None:
    """A method whose name has no parameter list still has its own row, and does not replace its neighbour's."""
    methods = _read(TEXT)
    assert len(methods) == 3 and "A$$Lambda/0xc6a3883ad1d74211d0ce6db95917a9520.apply(Object)" in methods, list(methods)
    assert methods["A$$Lambda/0xc6a3883ad1d74211d0ce6db95917a9520.apply(Object)"].loads == 1
    total = counts.total(methods)
    assert (total.loads, total.loop_loads, total.stores, total.calls) == (8 + 1, 5, 3 + 1, 3), total
    print("ok   a lambda's row is its own, and the totals add up")


def check_the_checks_can_fail() -> None:
    """A reader that counts a loop access under its plain name as well, and drops the rows of names it cannot parse, gives the
    totals the notes had for AWFY: more loads, fewer methods."""
    def old_reading(text: str) -> tuple[int, int]:
        loads = parsed = 0
        for line in text.splitlines():
            if line and not line[0].isspace():
                parsed += "(" in line and "$$Lambda" not in line
            elif "calls" in line and parsed:
                for item in line.split(" reads ")[1].split():
                    n = int(item.partition("×")[2] or 1)
                    loads += n + (n if "(loop)" in item else 0)
        return loads, parsed

    loads, parsed = old_reading(TEXT)
    assert (loads, parsed) != (counts.total(_read(TEXT)).loads, 3)
    print("ok   the old reading of the same text gives other totals")


def _read(text: str):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "counts.txt"
        path.write_text(text)
        return counts.read(path)
