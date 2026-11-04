"""One line per setting of the inliner and unroller sweep: what the setting costs Graal, and what fields gains over graal in it.

Usage:
    uv run python scripts/evaluation/inliner_summary.py graal-native/out/reproduction/<run>/inliner.txt

The input is the output of reproduce.sh's inliner stage. For each setting it shows the build of graal (total, the compile stage, the
stage the inliner runs in), what fields adds to the build, the run time of graal on AWFY (the first build, ms) and what fields does to
it: the total and Queens and Permute for each of the builds of fields, against the first graal build. The A/A column is the first graal
image timed again, the noise of one binary; "other graal" is the range of the other graal builds against the first. The loads and
branches left by place come from the table at the head of the file.
"""

import argparse
import re
from pathlib import Path


def stage_table(part: str) -> dict[str, list[float]]:
    return {m.group(1): [float(x) for x in m.group(2).split()] for m in re.finditer(r"^(graal|fields|fields-graal)\s+([-+\d. ]+)$", part, re.M)}


def run_time(part: str) -> tuple[list[str], dict[str, list[str]]]:
    m = re.search(r"^benchmark\s+(.*)\n((?:.*\n)*?)total\s+(.*)$", part, re.M)
    rows = {}
    for line in (m.group(2) + "total  " + m.group(3)).splitlines():
        cells = line.split()
        if cells:
            rows[cells[0]] = cells[1:]
    return m.group(1).split(), rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("inliner", type=Path)
    args = parser.parse_args()
    text = args.inliner.read_text()
    places = {}
    for line in text.splitlines():
        m = re.match(r"^(\S+)\s+(\d+)/(\d+)\s+[\d.]+%\s+\|\s+([-+]\d+) \(([-+\d.]+)%\)\s+([-+]\d+) \(([-+\d.]+)%\)", line)
        if m:
            places[m.group(1)] = (m.group(4), m.group(5), m.group(7))
    print(f"{'setting':20} | {'graal build s':>13} {'compile':>8} | {'fields adds s':>13} {'analysis':>8} | {'graal run ms':>12} | {'load places':>14} {'in loops':>8} | fields against graal, run time %: total (3 builds) | Queens | Permute")
    for part in re.split(r"^== setting ", text, flags=re.M)[1:]:
        name = part.split(":")[0]
        stages = stage_table(part)
        header, rows = run_time(part)
        base = float(rows["total"][0])
        fields = [i for i, h in enumerate(header[1:], 1) if h.startswith("fields")]
        def fcells(benchmark: str) -> str:
            return "/".join(rows[benchmark][i - 1].rstrip("%") for i in fields)
        g, f, d = stages["graal"], stages["fields"], stages["fields-graal"]
        pl = places.get(name, ("", "", ""))
        print(f"{name:20} | {g[9]:13.1f} {g[5]:8.1f} | {d[9]:+13.1f} {d[1]:+8.1f} | {base:12.1f} | {pl[0] + ' (' + pl[1] + '%)':>14} {pl[2] + '%':>8} | {fcells('total'):>26} | {fcells('Queens'):>20} | {fcells('Permute')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
