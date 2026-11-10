"""How the cost of the side-effect analysis grows with the size of the program: per program, what `fields` adds to the build of `graal`
(total seconds, per cent, the analysis stage, peak RSS) against the size of the image (compilation units, image heap objects).

Usage:
    uv run python scripts/evaluation/scaling.py graal-native/out [--table scaling.tsv] [--figure scaling.png]

Reads the logs of the builds image_sizes.py reads (AWFY's cost rounds, javac, PetClinic and the Barista applications; the builds of the inliner's
settings are left out: they are AWFY again), the sizes and provenance with image_sizes.py and the total, stages and peak RSS with cost.py. The
increment of a program is the median of its `fields` totals minus the median of its `graal` totals; it counts when the ranges over the rounds do
not overlap (the table says which). The fit is the line through the origin of the added seconds on the compilation units of the `graal` image, and
the same line without the two largest programs, to say whether they sit on it. --figure draws the table (it needs matplotlib, which nothing else
here uses). Nothing is built or run here.
"""

import argparse
import importlib.util
import math
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # image_sizes' dataclasses look their module up
    spec.loader.exec_module(module)
    return module


sizes = load("image_sizes")
cost = load("cost")


def log_of(b) -> Path:
    return b.directory / "build.log" if (b.directory / "build.log").exists() else b.directory / f"{b.config}.log"


def rows(out: Path):
    """One row per program with a finished build of both configurations, by the size of its `graal` image, and the (day, tool, fork) the builds are from."""
    result, sources = [], set()
    for group, programs in sizes.by_program(sizes.discover(out, {})).items():
        if "inliner" in group:
            continue
        for program, configs in programs.items():
            ok = {}
            for c in sizes.CONFIGS:
                found = [(b, cost.build(log_of(b))) for b in configs[c] if b.sizes]
                ok[c] = [(b, t) for b, t in found if "total" in t]
            if not ok["graal"] or not ok["fields"]:
                continue
            sources |= {(b.day, b.tool, b.fork) for c in ok for b, _ in ok[c]}
            total = {c: [t["total"] for _, t in ok[c]] for c in ok}
            analysis = {c: [t["analysis"] for _, t in ok[c]] for c in ok}
            rss = {c: [t["rss GiB"] for _, t in ok[c]] for c in ok}
            added = statistics.median(total["fields"]) - statistics.median(total["graal"])
            apart = max(total["graal"]) < min(total["fields"]) or max(total["fields"]) < min(total["graal"])
            result.append({
                "program": program,
                "rounds": f"{len(total['graal'])}/{len(total['fields'])}",
                "units": statistics.median([b.sizes.units for b, _ in ok["graal"]]),
                "objects": statistics.median([b.sizes.objects for b, _ in ok["graal"]]),
                "file_mib": statistics.median([b.sizes.file for b, _ in ok["graal"]]) / sizes.UNIT["MiB"],
                "graal_s": statistics.median(total["graal"]),
                "fields_s": statistics.median(total["fields"]),
                "added_s": added,
                "added_pct": 100 * added / statistics.median(total["graal"]),
                "analysis_added_s": statistics.median(analysis["fields"]) - statistics.median(analysis["graal"]),
                "rss_graal": statistics.median(rss["graal"]),
                "rss_added": statistics.median(rss["fields"]) - statistics.median(rss["graal"]),
                "apart": apart,
            })
    return sorted(result, key=lambda r: r["units"]), sources


def fit_origin(xs, ys):
    """Slope of y = k x through the origin, and the share of the variance of y it explains (1 - SSE / SST)."""
    k = sum(x * y for x, y in zip(xs, ys)) / sum(x * x for x in xs)
    mean = statistics.mean(ys)
    sse = sum((y - k * x) ** 2 for x, y in zip(xs, ys))
    sst = sum((y - mean) ** 2 for y in ys)
    return k, 1 - sse / sst


def fit_log(xs, ys):
    """Slope and R^2 of log y on log x."""
    lx, ly = [math.log(x) for x in xs], [math.log(y) for y in ys]
    mx, my = statistics.mean(lx), statistics.mean(ly)
    slope = sum((a - mx) * (b - my) for a, b in zip(lx, ly)) / sum((a - mx) ** 2 for a in lx)
    r = statistics.correlation(lx, ly)
    return slope, r * r


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("out", type=Path, help="graal-native/out")
    parser.add_argument("--table", type=Path, help="write the rows as tab-separated values")
    parser.add_argument("--figure", type=Path, help="draw the rows (needs matplotlib)")
    args = parser.parse_args()
    table, sources = rows(args.out)
    if len(table) < 3:
        print(f"error: {len(table)} programs with builds of both configurations below {args.out}; a fit needs three")
        return 1

    print(f"{'program':24} {'rounds':>6} {'units':>7} {'objects':>8} {'file MiB':>8} | {'graal s':>7} {'fields s':>8} {'added s':>8} {'added %':>7} {'analysis +s':>11} | {'rss graal':>9} {'rss +GiB':>8} | ranges")
    for r in table:
        print(f"{r['program']:24} {r['rounds']:>6} {r['units']:>7,.0f} {r['objects']:>8,.0f} {r['file_mib']:>8.1f} | {r['graal_s']:>7.1f} {r['fields_s']:>8.1f} {r['added_s']:>+8.1f} {r['added_pct']:>+6.1f}% {r['analysis_added_s']:>+11.1f} | {r['rss_graal']:>9.1f} {r['rss_added']:>+8.1f} | {'apart' if r['apart'] else 'overlap'}")
    print("\nbuilds from (day, tool, fork): " + "; ".join(f"{d} {t} {f}" for d, t, f in sorted(sources)))

    units = [r["units"] for r in table]
    added = [r["added_s"] for r in table]
    k, share = fit_origin(units, added)
    slope, r2 = fit_log(units, added)
    print(f"\n{len(table)} programs, {min(units):,.0f} to {max(units):,.0f} compilation units.")
    print(f"added seconds = {1000 * k:.2f} s per 1,000 units through the origin (explains {100 * share:.0f}% of the variance of the added seconds);")
    print(f"log-log slope {slope:.2f} (1 would be linear), R^2 {r2:.2f}.")
    if len(table) > 4:
        small = table[:-2]
        k_small, share_small = fit_origin([r["units"] for r in small], [r["added_s"] for r in small])
        big = ", ".join(f"{r['program']} {r['added_s']:+.1f} s against {k_small * r['units']:.1f} s" for r in table[-2:])
        print(f"without the two largest programs: {1000 * k_small:.2f} s per 1,000 units (explains {100 * share_small:.0f}%); what that line gives for them: {big}.")
    pct = [r["added_pct"] for r in table]
    print(f"added per cent of the build: median {statistics.median(pct):.1f}, range {min(pct):.1f} to {max(pct):.1f}; with units: correlation {statistics.correlation(units, pct):+.2f} (log units {statistics.correlation([math.log(u) for u in units], pct):+.2f}).")
    mem = [r["rss_added"] for r in table]
    print(f"peak RSS added: median {statistics.median(mem):+.1f} GiB, range {min(mem):+.1f} to {max(mem):+.1f}; relative to graal's: median {statistics.median(100 * r['rss_added'] / r['rss_graal'] for r in table):+.1f}%.")

    if args.table:
        keys = list(table[0])
        args.table.write_text("\t".join(keys) + "\n" + "\n".join("\t".join(str(r[key]) for key in keys) for r in table) + "\n")
    if args.figure:
        figure(table, k, args.figure)
    return 0


def figure(table, k, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker

    ink, soft, grid, surface, series = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb", "#2a78d6"
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "text.color": ink, "axes.labelcolor": soft, "xtick.color": soft, "ytick.color": soft})
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), facecolor=surface)
    label = {"awfy": "AWFY", "javac": "javac", "vanilla-hello-world": "vanilla", "petclinic": "PetClinic", "spring-petclinic": "spring-petclinic", "vertx-hello-world": "vertx"}
    units = [r["units"] for r in table]
    for ax, key, title, unit in ((axes[0], "added_s", "Added build time", "seconds"), (axes[1], "added_pct", "Added build time, per cent of the graal build", "per cent")):
        ax.set_facecolor(surface)
        ax.set_xscale("log")
        ys = [r[key] for r in table]
        if key == "added_s":
            ax.set_yscale("log")
            xs = [min(units) / 1.2, max(units) * 1.2]
            ax.plot(xs, [k * x for x in xs], color=soft, lw=1, ls=(0, (4, 3)), zorder=1)
            ax.text(xs[1], k * xs[1] * 0.17, f"{1000 * k:.2f} s per 1,000 units\n(through the origin)", ha="right", va="top", color=soft, fontsize=9)
        for apart, name in ((True, "ranges of the rounds apart"), (False, "ranges overlap (not told from the spread)")):
            points = [(r["units"], y) for r, y in zip(table, ys) if r["apart"] == apart]
            if points:
                ax.scatter(*zip(*points), s=46, facecolor=series if apart else surface, edgecolor=series, linewidth=1.5 if apart else 1.8, zorder=3, label=name)
        for r, y in zip(table, ys):
            if r["program"] in label:
                ax.annotate(label[r["program"]], (r["units"], y), textcoords="offset points", xytext=(6, -11 if r["program"] == "javac" else 5), fontsize=9, color=ink)
        ax.set_title(title, loc="left", fontsize=11, color=ink)
        ax.set_xlabel("compilation units in the graal image (log scale)")
        ax.set_ylabel(unit)
        ax.grid(True, color=grid, lw=0.6, zorder=0)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(grid)
        if key == "added_pct":
            ax.set_ylim(0, max(ys) * 1.15)
            ax.legend(loc="lower right", frameon=False, fontsize=9, labelcolor=soft)
        else:
            ax.yaxis.set_major_formatter(matplotlib.ticker.ScalarFormatter())
            ax.yaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
            ax.set_yticks([1, 2, 5, 10, 20, 40])
    fig.tight_layout()
    fig.savefig(path, dpi=160, facecolor=surface)


if __name__ == "__main__":
    raise SystemExit(main())
