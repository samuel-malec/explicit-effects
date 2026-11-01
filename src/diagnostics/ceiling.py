"""What the kill sets could free if some effects were made precise: how many methods still kill everything
when each combination of effects is left out of the kill sets. A measurement, never sound.

Usage:
    uv run python -m diagnostics.ceiling graal-native/out/awfy-eval/kills/export.json
    uv run python -m diagnostics.ceiling export.json --program deltablue,havlak --partition object-field

The effects are those of `effects.kills.IGNORABLE`: each on its own, then added one after the other (the three
the notes found in front of most opaque methods, then what lies behind them). A method is counted when its
kill set is everything (`any`); the program's methods are those outside the platform's packages, or the ones
`--program` names. The last row is the most the kill sets could do if the facts were exact about everything: an
upper bound to compare a build with, not a build to keep.
"""

import argparse
from pathlib import Path

from graal.graal_import import PointsToFacts, load_facts

from .blockers import in_program
from effects.kills import ANY, IGNORABLE, kills


#: The layers the notes found in front of most opaque methods, then what lies behind them, in the order they were found.
LAYERS = ("identity-hash", "class-initialization", "synchronization")
BEHIND = ("unresolved-calls", "other-effects", "calls-without-facts")


def ceiling(facts: PointsToFacts, program: list[str], partition: str = "field") -> list[tuple[str, int, int, int]]:
    """Rows of (what is left out, program methods killing everything, all methods killing everything, program
    methods): nothing; each effect on its own; then the effects added one after the other, from the three layers
    to all of them."""
    mine = [m for m in facts.methods if in_program(m, program)]
    rows = []

    def row(label: str, ignored: tuple[str, ...]) -> None:
        written = kills(facts, partition, ignored)
        rows.append((label, sum(written[m] == ANY for m in mine), sum(w == ANY for w in written.values()), len(mine)))

    row("nothing (as built)", ())
    for name in IGNORABLE:
        row(name, (name,))
    chain: tuple[str, ...] = ()
    for name in (*LAYERS, *BEHIND):
        chain += (name,)
        if len(chain) >= len(LAYERS):
            row("the three layers" if chain == LAYERS else f"+ {name}", chain)
    rows[-1] = (rows[-1][0] + " = everything", *rows[-1][1:])
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("export", type=Path, help="facts or graphs exported by graal-export or by the image builder")
    parser.add_argument("--program", default="", help="comma-separated method prefixes that are the program (default: outside the platform's packages)")
    parser.add_argument("--partition", choices=["field", "object-field"], default="field")
    parser.add_argument("--assumptions", help="the thread-escape assumptions to read, from an export made with all of them")
    args = parser.parse_args()

    facts = load_facts(args.export, args.assumptions)
    rows = ceiling(facts, [p for p in args.program.split(",") if p], args.partition)
    base_program, base_all = rows[0][1], rows[0][2]
    print(f"{rows[0][3]} program methods, {len(facts.methods)} in all; the kill of each effect left out in turn")
    print(f"{'left out':58} {'program':>8} {'freed':>6} {'all':>7} {'freed':>6}")
    for label, in_prog, everywhere, _ in rows:
        print(f"{label:58} {in_prog:>8} {base_program - in_prog:>6} {everywhere:>7} {base_all - everywhere:>6}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
