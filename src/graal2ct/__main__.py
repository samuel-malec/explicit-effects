"""Compiler Driver of Graal -> Cthu pipeline

Usage:
    cd graal-export && ./build.sh examples/Examples.java && \\
        DUMP_IR=out/examples.json ./run-dump.sh Examples && cd ..
    uv run graal2ct graal-export/out/examples.json --method forwardAcrossWritingCall
    uv run graal2ct graal-export/out/examples.json --partition field
    uv run graal2ct graal-export/out/examples.json --partition field --rules
    uv run graal2ct graal-export/out/objects.allocsens.json --partition object-field --rules

"""

import argparse
import sys
from pathlib import Path

from cthu import prelude
from cthu.ir import to_text
from cthu.ssu import check
from effects.signatures import PARTITIONERS, analyse, no_analysis
from graal.graal_import import load
from rules import memory

from .translate import Translation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("dump", type=Path)
    parser.add_argument("--method", default="", help="only methods whose name contains this")
    parser.add_argument("-o", "--out", type=Path, help="write the .ct text here instead of printing it")
    parser.add_argument("--partition", choices=["none", "field", "object", "object-field"], default="none",
                        help="none: one heap token in every method; field: a token per field and array kind; object: "
                             "per set of objects the points-to facts tell apart; object-field: per field of such a set")
    parser.add_argument("--rules", action="store_true",
                        help="then forward loads and remove dead stores, and list what they did")
    args = parser.parse_args()

    facts, graphs = load(args.dump)
    keys = [key for key in sorted(graphs) if args.method in key]
    effects = no_analysis() if args.partition == "none" else analyse(facts, PARTITIONERS[args.partition](facts))
    translation = Translation(graphs, effects)
    program = translation.translate(keys)
    rewrites = memory.apply(program) if args.rules else None
    text = to_text(program)

    if args.out:
        args.out.write_text(text + "\n")
    else:
        print(text)

    errors = check(program) + prelude.check(program, prelude.load())
    print(f"translated {len(program.structures)} of {len(keys)} method(s)", file=sys.stderr)
    for key, reason in translation.refused.items():
        print(f"  refused {key}: {reason}", file=sys.stderr)
    if rewrites:
        print(f"forwarded {len(rewrites.forwarded)} load(s), removed {len(rewrites.removed)} dead store(s)", file=sys.stderr)
        for what, done in (("forwarded", rewrites.forwarded), ("removed", rewrites.removed)):
            for line in done:
                print(f"  {what} {line}", file=sys.stderr)
    print(f"{'ok' if not errors else f'{len(errors)} error(s)'}", file=sys.stderr)
    for error in errors:
        print(f"    {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
