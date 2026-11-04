"""What our facts change in the code Graal leaves, measured with the inlining and the unrolling held apart.

Usage:
    uv run python scripts/evaluation/shape_metrics.py graal-native/out/awfy-ctl/{graal,fields}
    uv run python scripts/evaluation/shape_metrics.py graal-native/out/awfy-ctl/{graal,fields} --method Queens.placeQueen
    uv run python scripts/evaluation/shape_metrics.py --repeat graal-native/out/awfy-lap{,2,3}/graal    # what repeats between builds
    uv run python scripts/evaluation/shape_metrics.py --sweep graal-native/out/awfy-*                    # a line for each setting

Each image directory holds control.txt, sites.txt and, from the builder of 4 November on, shape.txt (the size of each
method's graph, the longest path through its control flow, and a hash of the inlining it was built from). The images
need -H:+TrackNodeSourcePosition. The first image is the one the second is compared with.

Graal inlines and unrolls differently once the kill sets change what a call may write, so counting every load and every
edge of two images mixes what our facts did with what the inliner and the unroller did in answer. Three cuts keep them
apart: (1) the methods that two images inlined in exactly the same way, whose differences cannot come from inlining
(without shape.txt, the inlining is read from the places of the loads and stores, which sees only the callees that have
one); (2) counts per 1,000 fixed nodes, so that a method that grew by inlining does not look as if it had more loads;
(3) load places: a load counted once however many copies unrolling and peeling made of it (the place is the field and the
inlining it came through, with the bytecode index of the load), which is what is left of the loads once the unroller is out of the way.
"""

import argparse
import re
from collections import Counter
from pathlib import Path

HIDDEN_CLASS = re.compile(r"/0x[0-9a-f]+")
CONTROL = ("blocks", "edges", "ifs", "splits", "loops", "exception calls", "deopts")
SHAPE = ("nodes", "fixed nodes", "path blocks", "path fixed", "deepest loop", "inlined sites", "inlining", "if places", "call places", "ifs unplaced")


def clean(text: str) -> str:
    """A hidden class's name ends in an address that changes from build to build; the content hash before it does not."""
    return HIDDEN_CLASS.sub("/0xH", text)


def table(path: Path, columns: tuple[str, ...]) -> dict[str, dict[str, object]]:
    rows: dict[str, dict[str, object]] = {}
    if not path.exists():
        return rows
    for line in path.read_text().splitlines():
        if line and not line.startswith("#"):
            method, *cells = line.split("\t")
            rows[clean(method)] = {c: (int(v) if v.lstrip("-").isdigit() else v) for c, v in zip(columns, cells)}
    return rows


class Image:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.control = table(directory / "control.txt", CONTROL)
        self.shape = table(directory / "shape.txt", SHAPE)
        self.inlined: dict[str, set[str]] = {}
        if (directory / "inlined.txt").exists():
            for line in (directory / "inlined.txt").read_text().splitlines():
                if line and not line.startswith("#"):
                    method, site = line.split("\t")
                    self.inlined.setdefault(clean(method), set()).add(clean(site))
        self.calls: dict[str, int] = {}
        method = ""
        for line in (directory / "counts.txt").read_text().splitlines():
            if line and not line.startswith(" "):
                method = clean(line)
            elif (found := re.search(r"\bcalls (\d+)", line)) and method and method not in self.calls:
                self.calls[method] = int(found.group(1))
        self.sites: dict[str, Counter] = {}
        for line in (directory / "sites.txt").read_text().splitlines():
            if line and not line.startswith("#"):
                method, kind, where, field, chain = line.split("\t")
                self.sites.setdefault(clean(method), Counter())[(kind, where, field, clean(chain))] += 1

    def count(self, method: str, kind: str, where: str | None = None) -> int:
        return sum(n for (k, w, _, _), n in self.sites.get(method, Counter()).items() if k == kind and (where is None or w == where))

    def inlining(self, method: str) -> object:
        """What the method was built from: the hash of its inlined call sites, else the callees that have a load or a store."""
        if method in self.shape and self.shape[method]["inlining"] not in (0, "0"):
            return self.shape[method]["inlining"]
        chains = {chain for (_, _, _, chain) in self.sites.get(method, Counter())}
        return ("from the accesses", frozenset(chains))


def methods_of(image: Image, exclude: list[str]) -> set[str]:
    return {m for m in image.control if not any(m.startswith(x) for x in exclude)}


def total(image: Image, methods: set[str]) -> dict[str, float]:
    sums: Counter = Counter()
    for m in methods:
        sums["loads"] += image.count(m, "load")
        sums["loads in loops"] += image.count(m, "load", "loop")
        sums["stores"] += image.count(m, "store")
        sums["calls"] += image.calls.get(m, 0)
        places = {(f, c) for (k, _, f, c) in image.sites.get(m, Counter()) if k == "load"}
        in_loop = {(f, c) for (k, w, f, c) in image.sites.get(m, Counter()) if k == "load" and w == "loop"}
        sums["load places"] += len(places)
        sums["load places in loops"] += len(in_loop)
        for column in ("blocks", "edges", "ifs", "loops"):
            sums[column] += image.control[m][column]
        if m in image.shape:
            for column, name in (("nodes", "nodes"), ("fixed nodes", "fixed nodes"), ("path blocks", "path (blocks)"), ("path fixed", "path (fixed nodes)"),
                                 ("if places", "if places"), ("call places", "call places"), ("ifs unplaced", "ifs unplaced")):
                if column in image.shape[m]:
                    sums[name] += image.shape[m][column]
            sums["deepest loop"] = max(sums["deepest loop"], image.shape[m]["deepest loop"])
    return sums


def show(label: str, base: Image, other: Image, methods: set[str]) -> None:
    before, after = total(base, methods), total(other, methods)
    columns = [c for c in ("loads", "loads in loops", "load places", "load places in loops", "stores", "blocks", "edges", "ifs", "if places", "loops", "calls", "call places", "path (blocks)", "path (fixed nodes)", "ifs unplaced") if c in before]
    print(f"\n{label}: {len(methods)} methods")
    print(f"  {'':10}" + "".join(f"{c[:18]:>19}" for c in columns))
    for name, sums in (("first", before), ("second", after)):
        print(f"  {name:10}" + "".join(f"{sums[c]:>19,.0f}" for c in columns))
    print(f"  {'change':10}" + "".join(f"{after[c] - before[c]:>+19,.0f}" for c in columns))
    print(f"  {'':10}" + "".join(f"{(100 * (after[c] - before[c]) / before[c] if before[c] else 0):>+18.1f}%" for c in columns))
    if "fixed nodes" in before and before["fixed nodes"]:
        per = [c for c in ("loads", "loads in loops", "edges", "ifs") if c in before]
        print("  per 1,000 fixed nodes: " + ", ".join(
            f"{c} {1000 * before[c] / before['fixed nodes']:.1f} -> {1000 * after[c] / after['fixed nodes']:.1f} "
            f"({100 * ((after[c] / after['fixed nodes']) / (before[c] / before['fixed nodes']) - 1) if before[c] else 0:+.1f}%)" for c in per))


def call_sites(chain: str) -> list[str]:
    """The inlined call sites a place came through, as the builder names them in inlined.txt: callee < caller@bci < ...."""
    frames = chain.split(" < ")
    return [" < ".join([frames[i].rsplit("@", 1)[0]] + frames[i + 1:]) for i in range(len(frames) - 1)]


def keys(image: Image, method: str, kind: str) -> dict[tuple[str, str], Counter]:
    """The places of a method, (field, inlining chain) -> how many copies are in a loop (`loop`) and not (`flat`)."""
    found: dict[tuple[str, str], Counter] = {}
    for (k, where, field, chain), n in image.sites.get(method, Counter()).items():
        if k == kind:
            found.setdefault((field, chain), Counter())[where] += n
    return found


def matched(base: Image, other: Image, methods: set[str], kind: str) -> Counter:
    """The places of the methods one by one, told apart by whether the inlining that brought them was kept in the other image.

    both: the place is in both images. gone / new, inlining kept: it is in one image only, although every call site it came
    through is inlined in the other too, so its load or store was removed (or made) by what the images did with the code, not by
    what was inlined. gone / new with its inlining: it is in one image only and some call site it came through is not inlined in
    the other image: the inliner decided differently. Copies are counted separately: copies gone is the loads of the places in both
    that have fewer copies, plus the copies of the places that are gone.
    """
    found: Counter = Counter()
    for m in methods:
        before, after = keys(base, m, kind), keys(other, m, kind)
        for key in before.keys() | after.keys():
            b, a = before.get(key, Counter()), after.get(key, Counter())
            if key in before and key in after:
                found["places in both"] += 1
                found["loop places before"] += bool(b["loop"])
                found["loop places after"] += bool(a["loop"])
                found["copies gone"] += max(0, sum(b.values()) - sum(a.values()))
                found["copies new"] += max(0, sum(a.values()) - sum(b.values()))
                if b["loop"] and not a["loop"]:
                    found["left a loop, still there"] += 1
                elif a["loop"] and not b["loop"]:
                    found["entered a loop"] += 1
            elif key in before:
                kept = all(site in other.inlined.get(m, set()) for site in call_sites(key[1]))
                found["gone, inlining kept" if kept else "gone with its inlining"] += 1
                if kept:
                    found["loop places before"] += bool(b["loop"])
                found["copies gone"] += sum(b.values())
                if b["loop"]:
                    found["in a loop, gone" if kept else "in a loop, gone with its inlining"] += 1
            else:
                kept = all(site in base.inlined.get(m, set()) for site in call_sites(key[1]))
                found["new, inlining kept" if kept else "new with its inlining"] += 1
                if kept:
                    found["loop places after"] += bool(a["loop"])
                found["copies new"] += sum(a.values())
    return found


def matched_line(base: Image, other: Image, methods: set[str], kind: str) -> str:
    found = matched(base, other, methods, kind)
    in_before = found["places in both"] + found["gone, inlining kept"]
    change = found["new, inlining kept"] - found["gone, inlining kept"]
    return (f"{kind} places whose inlining both images have: {in_before} -> {in_before + change} ({change:+d}, {100 * change / in_before if in_before else 0:+.1f}%); "
            f"gone {found['gone, inlining kept']}, new {found['new, inlining kept']}; left a loop and still there {found['left a loop, still there']}, "
            f"in a loop and gone {found['in a loop, gone']}, entered a loop {found['entered a loop']}; "
            f"with the inlining decided differently: gone {found['gone with its inlining']}, new {found['new with its inlining']}; "
            f"copies gone {found['copies gone']}, new {found['copies new']}")


def compare(args: argparse.Namespace) -> int:
    base, other = Image(args.images[0]), Image(args.images[1])
    common = methods_of(base, args.exclude) & methods_of(other, args.exclude)
    same = {m for m in common if base.inlining(m) == other.inlining(m)}
    source = "the inlining hash of shape.txt" if base.shape and other.shape else "the inlining read from the loads and stores"
    print(f"{args.images[0]} -> {args.images[1]}; excluded: {', '.join(args.exclude) or 'nothing'}")
    print(f"{len(common)} methods in both, {len(same)} with the same inlining ({source})")
    show("all methods in both", base, other, common)
    show("same inlining", base, other, same)
    differing = sorted(common - same)
    show("different inlining (the methods the first cut leaves out)", base, other, set(differing))
    held = sum(base.count(m, "load") for m in differing)
    every = sum(base.count(m, "load") for m in common)
    print(f"  the methods with different inlining hold {held} of {every} loads of the first image ({100 * held / every:.1f}%) and {len(differing)} of {len(common)} methods")
    if base.inlined and other.inlined:
        print("\nplace by place, with the inlining matched call site by call site (all common methods, whatever their inlining):")
        for kind in ("load", "store"):
            print("  " + matched_line(base, other, common, kind))
    else:
        print("\n(no inlined.txt: the builds are from a builder without it, so places cannot be matched call site by call site)")
    print(f"\ndifferent inlining ({len(differing)} methods), by loads in the first image:")
    for m in sorted(differing, key=lambda m: -base.count(m, "load"))[: args.methods]:
        print(f"  loads {base.count(m, 'load')} -> {other.count(m, 'load')}, edges {base.control[m]['edges']} -> {other.control[m]['edges']}, "
              f"calls-with-exception {base.control[m]['exception calls']} -> {other.control[m]['exception calls']}  {m[:70]}")
    for prefix in args.method:
        for m in sorted(common):
            if m.startswith(prefix):
                print(f"\n{m}: same inlining {m in same}")
                for label, image in (("first", base), ("second", other)):
                    shape = image.shape.get(m, {})
                    print(f"  {label:7} loads {image.count(m, 'load')} ({image.count(m, 'load', 'loop')} in loops), edges {image.control[m]['edges']}, blocks {image.control[m]['blocks']}, "
                          f"loops {image.control[m]['loops']}" + (f", fixed nodes {shape['fixed nodes']}, longest path {shape['path blocks']} blocks / {shape['path fixed']} fixed nodes, "
                                                                 f"inlined sites {shape['inlined sites']}" if shape else ""))
    return 0


def sweep(args: argparse.Namespace) -> int:
    """One line for each setting (a directory holding graal/ and fields/): what changed, place by place, whatever the inlining."""
    print(f"{'setting':20} {'same/both':>9} {'excluded':>8} | {'load places':>16} {'in loops':>16} {'hoisted':>7} {'differs':>11} | {'if places':>16} {'call places':>12} | {'raw loads':>16} {'raw edges':>16}")
    print(f"{'':20} {'methods':>9} {'loads':>8} | all methods, matched call site by call site{'':6} | same-inlining methods{'':8} | same-inlining methods")
    for directory in args.images:
        try:
            base, other = Image(directory / "graal"), Image(directory / "fields")
        except FileNotFoundError:
            print(f"{directory.name:20} (no images)")
            continue
        common = methods_of(base, args.exclude) & methods_of(other, args.exclude)
        same = {m for m in common if base.inlining(m) == other.inlining(m)}
        held = sum(base.count(m, "load") for m in common - same)
        every = sum(base.count(m, "load") for m in common)
        found = matched(base, other, common, "load")
        in_before = found["places in both"] + found["gone, inlining kept"]
        change = found["new, inlining kept"] - found["gone, inlining kept"]
        loop_change = found["loop places after"] - found["loop places before"]
        before, after = total(base, same), total(other, same)
        def cell(name: str) -> str:
            delta = after[name] - before[name]
            return f"{delta:+,.0f} ({100 * delta / before[name] if before[name] else 0:+.1f}%)"
        print(f"{directory.name.removeprefix('awfy-'):20} {len(same):>4}/{len(common):<4} {100 * held / every:>11.1f}% | "
              f"{change:+5d} ({100 * change / in_before if in_before else 0:+.1f}%) {loop_change:+5d} ({100 * loop_change / found['loop places before'] if found['loop places before'] else 0:+.1f}%) "
              f"{found['left a loop, still there']:>11} {found['gone with its inlining']:>4},{found['new with its inlining']:<4} | "
              f"{cell('if places'):>16} {cell('call places'):>11} | {cell('loads'):>20} {cell('edges'):>14}")
    return 0


def repeat(args: argparse.Namespace) -> int:
    """Which methods have different numbers in builds of the same image."""
    images = [Image(d) for d in args.images]
    methods = set().union(*(methods_of(i, []) for i in images))
    print(f"{len(images)} builds, {len(methods)} methods")
    for column in CONTROL + ("loads", "stores") + (SHAPE[:-1] if all(i.shape for i in images) else ()):
        def value(image: Image, m: str):
            if column in ("loads", "stores"):
                return image.count(m, column[:-1])
            if column in CONTROL:
                return image.control.get(m, {}).get(column)
            return image.shape.get(m, {}).get(column)
        varying = [m for m in methods if len({value(i, m) for i in images}) > 1]
        print(f"  {column:16} differs in {len(varying)} methods" + (": " + ", ".join(m[:40] for m in sorted(varying)[:5]) if varying else ""))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("images", nargs="+", type=Path, help="image directories (graal-native/out/<name>/<mode>)")
    parser.add_argument("--sweep", action="store_true", help="one line per setting: the directories hold graal/ and fields/ each")
    parser.add_argument("--repeat", action="store_true", help="compare builds of one image with each other instead of two images")
    parser.add_argument("--exclude", action="append", default=["Awfy.main"], help="method name prefixes left out (default: Awfy.main, the harness, whose size varies between builds)")
    parser.add_argument("--method", action="append", default=[], help="a method name prefix to list in detail")
    parser.add_argument("--methods", type=int, default=6, help="how many methods with different inlining to list")
    args = parser.parse_args()
    return sweep(args) if args.sweep else repeat(args) if args.repeat else compare(args)


if __name__ == "__main__":
    raise SystemExit(main())
