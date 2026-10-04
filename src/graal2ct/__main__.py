"""Compiler Driver of Graal -> Cthu pipeline

Usage:
    cd graal-export && ./build.sh examples/TokenExamples.java && \\
        DUMP_IR=out/token-examples.json ./run-dump.sh TokenExamples && cd ..
    PYTHONPATH=src python3 -m graal2ct graal-export/out/token-examples.json --method resetCounter

"""

import argparse
import sys
from pathlib import Path

from cthu import prelude
from cthu.ir import to_text
from cthu.ssu import check
from graal.graal_import import load

from .translate import Translation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("dump", type=Path)
    parser.add_argument("--method", default="", help="only methods whose name contains this")
    parser.add_argument("-o", "--out", type=Path, help="write the .ct text here instead of printing it")
    args = parser.parse_args()

    _, graphs = load(args.dump)
    keys = [key for key in sorted(graphs) if args.method in key]
    translation = Translation(graphs)
    program = translation.translate(keys)
    text = to_text(program, header=f"graal2ct {args.dump.name}: Graal IR in Cthulhu, one heap token")
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
