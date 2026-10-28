"""Compiler Driver of Graal -> Cthu pipeline

Usage:
    cd graal-export && ./build.sh corpus/Examples.java && \\
        DUMP_IR=out/examples.json ./run-dump.sh Examples && cd ..
    uv run graal2ct graal-export/out/examples.json --method forwardAcrossWritingCall
    uv run graal2ct graal-export/out/examples.json --partition field
    uv run graal2ct graal-export/out/examples.json --partition field --shape
    uv run graal2ct graal-export/out/objects.allocsens.json --partition object-field --shape

"""

import argparse
import sys
from pathlib import Path

from cthu import prelude
from cthu.ir import to_text
from cthu.ssu import check
from effects.signatures import PARTITIONERS, analyse, no_analysis
from graal.graal_import import load

from .shape import straighten
from .translate import Translation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("dump", type=Path)
    parser.add_argument("--method", default="", help="only methods whose name contains this")
    parser.add_argument("-o", "--out", type=Path, help="write the .ct text here instead of printing it")
    parser.add_argument("--partition", choices=["none", "field", "object", "object-field"], default="none",
                        help="none: one heap token in every method; field: a token per field and array kind; object: "
                             "per set of objects the points-to facts tell apart; object-field: per field of such a set")
    parser.add_argument("--shape", action="store_true",
                        help="then make the code straight-line (a branch to an arm that throws becomes a guard, a block "
                             "that one jump reaches joins the λ that jumps), with no forwarding and no dead stores")
    parser.add_argument("--types", action="store_true",
                        help="give each λ's parameter and result types too, which makes the text much longer")
    args = parser.parse_args()

    facts, graphs = load(args.dump)
    keys = [key for key in sorted(graphs) if args.method in key]
    effects = no_analysis() if args.partition == "none" else analyse(facts, PARTITIONERS[args.partition](facts))
    translation = Translation(graphs, effects)
    program = translation.translate(keys)
    if args.shape:
        straighten(program)
    text = to_text(program, types=args.types)

    if args.out:
        args.out.write_text(text + "\n")
    else:
        print(text)

    errors = check(program) + prelude.check(program, prelude.load())
    print(f"translated {len(program.structures)} of {len(keys)} method(s)", file=sys.stderr)
    for key, reason in translation.refused.items():
        print(f"  refused {key}: {reason}", file=sys.stderr)
    print(f"{'ok' if not errors else f'{len(errors)} error(s)'}", file=sys.stderr)
    for error in errors:
        print(f"    {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
