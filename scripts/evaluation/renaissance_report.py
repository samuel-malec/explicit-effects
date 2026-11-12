"""The run time of the Renaissance images of graal and fields: what renaissance_run.py kept, per benchmark.

Usage:
    uv run python scripts/evaluation/renaissance_report.py graal-native/out/renaissance-run/<day> [more result directories] [--tsv runs.tsv]

The score of one process is the mean of its last N iterations, N as mx takes it (min(20, iterations, max(6, 40% of the iterations)),
getExtraIterationCount in mx_benchmark.py); the score of an image is the median over its processes (the repeats); the score of a
configuration is the median over its images (the rounds, three builds of the same bundle), with the range of the rounds next to it.
`fields` differs from `graal` outside the noise when the ranges of the rounds do not overlap, as for the build times; with the
processes of one image spread over the whole run, the range of the rounds also contains the drift of the machine. The first
iteration is reported on its own. A process that failed (exit status, a missing or failed iteration) is listed and left out. So is a
process named in --exclude (a file of lines `benchmark config round repeat reason`; `#` starts a comment), which is for a process that
something else on the machine disturbed; the process that was run again has a repeat number of its own.
Nothing is built or run here.
"""

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path


def extra_iterations(iterations: int) -> int:
    return min(20, iterations, max(6, int(iterations * 0.4)))


def score(times: list[float]) -> float:
    n = extra_iterations(len(times))
    return statistics.mean(times[-n:])


def read(directories: list[Path]) -> list[dict]:
    rows = []
    for d in directories:
        path = d / "results.jsonl" if d.is_dir() else d
        rows += [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return rows


def excluded(path: Path | None) -> dict[tuple[str, str, int, int], str]:
    """(benchmark, config, round, repeat) -> the reason, from the lines of --exclude."""
    found = {}
    for line in path.read_text().splitlines() if path else []:
        line = line.split("#")[0].strip()
        if line:
            benchmark, config, round_, repeat, *reason = line.split()
            found[(benchmark, config, int(round_), int(repeat))] = " ".join(reason)
    return found


def span(values: list[float]) -> str:
    return f"{min(values):.1f}-{max(values):.1f}" if len(values) > 1 else "-"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("results", nargs="+", type=Path, help="result directories (or results.jsonl files) of renaissance_run.py")
    parser.add_argument("--tsv", type=Path, help="write one row per benchmark")
    parser.add_argument("--exclude", type=Path, help="processes to leave out, one `benchmark config round repeat reason` per line")
    args = parser.parse_args()

    rows = read(args.results)
    left_out = excluded(args.exclude)
    runs: dict[str, dict[str, dict[int, list[float]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    firsts: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    failures, disturbed = [], []
    for r in rows:
        if (r["benchmark"], r["config"], r["round"], r["repeat"]) in left_out:
            disturbed.append(r)
            continue
        if r["status"] != "ok":
            failures.append(r)
            continue
        runs[r["benchmark"]][r["config"]][r["round"]].append(score(r["times_ms"]))
        firsts[r["benchmark"]][r["config"]].append(r["times_ms"][0])

    header = f"{'benchmark':18} {'iters':>5} {'procs':>9} | {'graal ms':>9} {'rounds':>13} | {'fields ms':>9} {'rounds':>13} | {'fields-graal':>12} {'outside':>8} | {'1st iter graal':>14} {'fields':>9}"
    print(header)
    table = []
    for benchmark in runs:
        per_config = {}
        for config in ("graal", "fields"):
            images = {k: statistics.median(v) for k, v in runs[benchmark][config].items()}
            per_config[config] = images
        if not per_config["graal"] or not per_config["fields"]:
            continue
        g, f = per_config["graal"], per_config["fields"]
        gm, fm = statistics.median(g.values()), statistics.median(f.values())
        outside = max(g.values()) < min(f.values()) or max(f.values()) < min(g.values())
        procs = f"{sum(len(v) for v in runs[benchmark]['graal'].values())}+{sum(len(v) for v in runs[benchmark]['fields'].values())}"
        n = next(r for r in rows if r["benchmark"] == benchmark)["iterations_asked"]
        first_g, first_f = statistics.median(firsts[benchmark]["graal"]), statistics.median(firsts[benchmark]["fields"])
        diff = 100 * (fm - gm) / gm
        print(f"{benchmark:18} {n:>5} {procs:>9} | {gm:>9.1f} {span(list(g.values())):>13} | {fm:>9.1f} {span(list(f.values())):>13} | {diff:>+11.1f}% {'yes' if outside else 'no':>8} | {first_g:>14.0f} {first_f:>9.0f}")
        table.append((benchmark, n, procs, gm, span(list(g.values())), fm, span(list(f.values())), diff, outside, first_g, first_f))
    if failures:
        print("\nfailed processes (left out):")
        for r in failures:
            print(f"  {r['benchmark']} {r['config']} r{r['round']} #{r['repeat']}: {r['status']}, exit {r.get('exit')}, {len(r.get('times_ms', []))} of {r['iterations_asked']} iterations")
    if disturbed:
        print("\nleft out by --exclude:")
        for r in disturbed:
            print(f"  {r['benchmark']} {r['config']} r{r['round']} #{r['repeat']}: {left_out[(r['benchmark'], r['config'], r['round'], r['repeat'])]}")
    if args.tsv:
        lines =["benchmark\titerations\tprocesses\tgraal_ms\tgraal_rounds\tfields_ms\tfields_rounds\tdiff_percent\toutside_range\tfirst_graal_ms\tfirst_fields_ms"]
        lines += ["\t".join(str(x) if not isinstance(x, float) else f"{x:.3f}" for x in row) for row in table]
        args.tsv.write_text("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
