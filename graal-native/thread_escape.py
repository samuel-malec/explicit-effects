"""The table of graal-native/thread-escape.sh: for each example and analysis, whether its Item is
shared under each set of assumptions: the first six are cumulative, none to all five; "only" is the
two that the plain controls need, vm-code and entry-points, and nothing else.

Usage:
    uv run python graal-native/thread_escape.py graal-native/out/thread-escape [Example ...]
"""

import sys
from pathlib import Path

from graal.graal_import import load_facts

LAYERS = ["none", "thread-confined", "thread-confined,vm-fields", "thread-confined,vm-fields,vm-code", "thread-confined,vm-fields,vm-code,handler-references",
          "thread-confined,vm-fields,vm-code,handler-references,entry-points", "vm-code,entry-points"]
SHORT = ["none", "+thread", "+fields", "+code", "+refs", "+entry", "only"]


def item_shared(export: Path, example: str, analysis: str, layer: str) -> str:
    from effects.publication import item_shared as shared

    return shared(load_facts(export, layer), example)


def main() -> int:
    out = Path(sys.argv[1])
    examples = sys.argv[2:] or sorted({p.name.rsplit(".", 1)[0] for p in out.iterdir() if p.is_dir()})
    analyses = sorted({p.name.rsplit(".", 1)[1] for p in out.iterdir() if p.is_dir()}, key=["insens", "allocsens", "_1obj", "_2obj1h"].index)
    width = max(len(e) for e in examples) + 2
    print(f"{'':{width}}" + "".join(f"{a:^{8 * len(LAYERS)}}" for a in analyses))
    print(f"{'':{width}}" + "".join("".join(f"{s:>8}" for s in SHORT) for _ in analyses))
    for example in examples:
        row = f"{example:{width}}"
        for analysis in analyses:
            export = out / f"{example}.{analysis}" / "out" / "export.json"
            for layer in LAYERS:
                row += f"{item_shared(export, example, analysis, layer) if export.exists() else '-':>8}"
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
