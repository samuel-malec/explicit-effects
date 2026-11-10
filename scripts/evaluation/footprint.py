"""What adopting the feature costs in code and in use: the size of the fork's change to Graal against upstream, the options it adds, the command
line that switches it on, and the size and requirements of the tool the builder runs.

Usage:
    uv run python scripts/evaluation/footprint.py [--fork DIR] [--branch side-effect-analysis] [--upstream upstream/master]

--fork is a checkout of the fork (default: $GRAAL_HOME, else the graal submodule of this repository). The base is the merge base of the fork's branch
with the local ref of upstream, which is not fetched here: its head is as old as the last `git fetch upstream` of that checkout, which the output says.
Counts are of `git diff --numstat` from the base; the tool is this checkout. Nothing is built or run.
"""

import argparse
import os
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FEATURE = "substratevm/src/com.oracle.svm.hosted/src/com/oracle/svm/hosted/sideeffects/SideEffectAnalysisFeature.java"
OPTION = re.compile(r"@Option\(help = (.*?)stability = OptionStability\.EXPERIMENTAL\)\s*//?\s*public static final HostedOptionKey<([\w<>,]+)> (\w+) = new HostedOptionKey<>\((.*?)\);", re.S)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def numstat(repo: Path, base: str, branch: str, *extra: str) -> list[tuple[int, int, str]]:
    rows = []
    for line in git(repo, "diff", "--numstat", *extra, base, branch).splitlines():
        added, removed, path = line.split("\t", 2)
        rows.append((int(added), int(removed), path))
    return rows


def total(rows) -> str:
    return f"{len(rows)} files, +{sum(r[0] for r in rows):,} -{sum(r[1] for r in rows):,}"


def python_lines(directory: Path) -> tuple[int, int]:
    files = sorted(directory.rglob("*.py"))
    return len(files), sum(len(f.read_text().splitlines()) for f in files)


def options(feature: Path) -> list[tuple[str, str, str, str]]:
    """(kind, name, type, default) of the feature's options; a control is an option whose help says it must break images or breaks them on purpose."""
    found = []
    for m in OPTION.finditer(feature.read_text()):
        text = re.sub(r'"\s*\+\s*"', "", re.sub(r"//\s*", "", m[1])).strip().strip(",").strip('"')
        kind = "control" if re.match(r"(Control|Have every|Have narrowed)", text) else "option"
        found.append((kind, m[3], m[2], m[4]))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--fork", type=Path, default=Path(os.environ.get("GRAAL_HOME") or REPO / "graal"))
    parser.add_argument("--branch", default="side-effect-analysis")
    parser.add_argument("--upstream", default="upstream/master")
    args = parser.parse_args()
    if not (args.fork / FEATURE).exists():
        print(f"error: {args.fork / FEATURE} does not exist: --fork (or GRAAL_HOME) must be a checkout of the fork")
        return 1

    base = git(args.fork, "merge-base", args.branch, args.upstream)
    print(f"fork {args.fork}, branch {args.branch} at {git(args.fork, 'rev-parse', '--short=11', args.branch)}")
    print(f"base: {git(args.fork, 'log', '-1', '--format=%h %ad', '--date=short', base)} (merge base with the local ref {args.upstream}; its head: "
          f"{git(args.fork, 'log', '-1', '--format=%h %ad', '--date=short', args.upstream)}; {git(args.fork, 'rev-list', '--count', f'{base}..{args.upstream}')} commits of upstream since)")
    print(f"commits on the branch since the base: {git(args.fork, 'rev-list', '--count', f'{base}..{args.branch}')}\n")

    everything = numstat(args.fork, base, args.branch)
    added = numstat(args.fork, base, args.branch, "--diff-filter=A")
    modified = numstat(args.fork, base, args.branch, "--diff-filter=M")
    deleted = git(args.fork, "diff", "--name-only", "--diff-filter=D", base, args.branch).splitlines()
    print(f"change to Graal: {total(everything)}; {len(deleted)} files deleted")
    print(f"  new files:      {total(added)}")
    print(f"  existing files: {total(modified)}   <- the lines that change Graal's own code")
    for name, prefix in (("compiler (jdk.graal.compiler)", "compiler/"), ("points-to analysis (com.oracle.graal.pointsto)", "substratevm/src/com.oracle.graal.pointsto/"),
                         ("Native Image (com.oracle.svm.hosted)", "substratevm/src/com.oracle.svm.hosted/"), ("build files", "substratevm/mx.substratevm/")):
        print(f"  {name:48} new: {total([r for r in added if r[2].startswith(prefix)]):28} existing: {total([r for r in modified if r[2].startswith(prefix)])}")
    other = [r for r in everything if not r[2].startswith(("compiler/", "substratevm/"))]
    print(f"  outside compiler/ and substratevm/: {total(other)} ({', '.join(r[2] for r in other)})\n")

    found = options(args.fork / FEATURE)
    controls = [o for o in found if o[0] == "control"]
    print(f"options of the feature: {len(found)} ({len(found) - len(controls)} to use it, {len(controls)} controls that must break images)")
    print("  controls: " + ", ".join(o[1] for o in controls))
    print("  to use it: " + ", ".join(f"{o[1]} ({o[3]})" for o in found if o[0] == "option"))
    print("  the command line of the `fields` build (scripts/frameworks/bundle.sh): -H:+UnlockExperimentalVMOptions -H:+SideEffectAnalysis "
          "-H:SideEffectAnalysisOutput=<dir> -H:SideEffectAnalysisTool=<checkout of the tool> -H:SideEffectAnalysisUv=<uv>\n")

    files, lines = python_lines(REPO / "src")
    tests = python_lines(REPO / "test")
    pyproject = (REPO / "pyproject.toml").read_text()
    python = re.search(r'requires-python = "([^"]+)"', pyproject)[1]
    dependencies = re.search(r"^dependencies = (\[.*?\])", pyproject, re.M | re.S)[1]
    print(f"the tool (this checkout, {git(REPO, 'rev-parse', '--short', 'HEAD')} of {git(REPO, 'branch', '--show-current')}):")
    print(f"  src/: {files} Python files, {lines:,} lines; test/: {tests[0]} files, {tests[1]:,} lines")
    print(f"  Python {python}, run with uv; dependencies of the package: {dependencies}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
