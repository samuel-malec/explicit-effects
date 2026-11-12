"""Run the Renaissance images the builds left, one process at a time, and keep what the harness prints for every iteration. Run on
pontos04, with nothing else running; reads the images, builds nothing.

Usage:
    python3 renaissance_run.py [--builds graal-native/out/renaissance] [--out graal-native/out/renaissance-run]
        [--benchmarks a,b] [--configs graal,fields] [--rounds 1,2,3] [--repeats 5] [--first-repeat 1] [--cpus 4-7] [--heap 8g]

Per benchmark the images take turns (graal r1, fields r1, graal r2, ..., then again for the next repeat), so that a drift of the machine
is spread over the images instead of falling on one; each process is pinned to --cpus and starts only when the machine is idle (below 1.5 busy cores over five seconds). A
process runs the benchmark for the number of iterations mx runs it (the table below, from mx_sdk_benchmark.py of the graal tree) and
the harness validates the result of every iteration; a process whose exit status is not 0, or that prints no completed iteration, is
a failure and is listed, not dropped. Every iteration's time is kept, the first one included: an image has no JIT, but its first
iterations are still slower (page-in, heap growth, lazy class initialization).
"""

import argparse
import json
import os
import re
import resource
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
BUILDS = REPO / "graal-native/out/renaissance"
CONFIGS = ("graal", "fields")

# iterations per benchmark, as mx runs them (_renaissanceConfig in sdk/mx.sdk/mx_sdk_benchmark.py)
ITERATIONS = {
    "akka-uct": 24, "dotty": 50, "finagle-chirper": 90, "finagle-http": 12, "fj-kmeans": 30, "future-genetic": 50, "mnemonics": 16,
    "par-mnemonics": 16, "philosophers": 30, "reactors": 10, "rx-scrabble": 80, "scala-doku": 20, "scala-kmeans": 50, "scala-stm-bench7": 60,
    "scrabble": 50,
}
# `====== scrabble (renaissance) [default], iteration 3 completed (12.345 ms) ======`
COMPLETED = re.compile(r"^={6} (\S+) \(\S+\) \[\S+\], iteration (\d+) completed \((\d+(?:\.\d+)?) ms\) ={6}")
FAILED = re.compile(r"^={6} (\S+) \(\S+\) \[\S+\], iteration (\d+) failed")


def extra_run_args(benchmark: str, image: Path) -> list[str]:
    """What mx adds to the image's command line for a benchmark (_extra_native_run_args in mx_substratevm_benchmark.py)."""
    if benchmark == "dotty":
        # -H:+AllowJRTFileSystem needs java.home at run time, and dotty compiles with the classpath of the standalone jar
        extracted = Path.home() / ".mx/cache"
        jar = next(extracted.glob("RENAISSANCE_0.16.0_*/renaissance.extracted/single/dotty.jar"), None)
        return [f"-Djava.home={os.environ['JAVA_HOME']}", f"-Djava.class.path={jar}"]
    return []


def busy_cores(seconds: int = 5) -> float:
    """How many cores the machine keeps busy over the next few seconds (from /proc/stat: everything but idle and iowait)."""
    def sample() -> tuple[int, int]:
        fields = [int(x) for x in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
        return sum(fields), fields[3] + fields[4]
    total0, idle0 = sample()
    time.sleep(seconds)
    total1, idle1 = sample()
    return (1 - (idle1 - idle0) / (total1 - total0)) * (os.cpu_count() or 1)


def quiet(limit: float = 1.5, patience: int = 240) -> bool:
    """Wait until the machine is idle (below `limit` busy cores: the timings are of a machine with nothing else running). The load
    average would not do: the previous process of this run keeps it above 2 for a minute after it has ended."""
    for _ in range(patience):
        if busy_cores() < limit:
            return True
        time.sleep(10)
    return False


def run_once(benchmark: str, config: str, round_: int, repeat: int, image: Path, args: argparse.Namespace, scratch: Path) -> dict:
    iterations = args.iterations or ITERATIONS[benchmark]
    result = {"benchmark": benchmark, "config": config, "round": round_, "repeat": repeat, "iterations_asked": iterations}
    if not image.exists():
        return {**result, "status": "no image", "image": str(image)}
    image = image.resolve()
    work = scratch / f"{benchmark}-{config}-r{round_}-{repeat}"
    work.mkdir(parents=True)
    command = ["taskset", "-c", args.cpus, str(image), f"-Xmx{args.heap}", f"-Xms{args.heap}", *extra_run_args(benchmark, image),
               "-r", str(iterations), benchmark]
    result["quiet"] = quiet()
    result["load_before"] = os.getloadavg()[0]  # for the record: it includes the previous process of this run
    started = time.monotonic()
    with (work / "output.log").open("wb") as out:
        process = subprocess.Popen(command, cwd=work, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            status = process.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, 9)
            process.wait()
            status = f"killed after {args.timeout} s"
    result["wall_s"] = round(time.monotonic() - started, 2)
    result["exit"] = status
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    result["max_rss_mib_so_far"] = round(usage.ru_maxrss / 1024, 1)  # the largest of all children so far: read it as a ceiling
    times, failed = [], []
    for line in (work / "output.log").read_text(errors="replace").splitlines():
        if m := COMPLETED.match(line):
            times.append(float(m.group(3)))
        elif m := FAILED.match(line):
            failed.append(int(m.group(2)))
    result["times_ms"] = times
    result["failed_iterations"] = failed
    result["status"] = "ok" if status == 0 and len(times) == iterations and not failed else "failed"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--builds", type=Path, default=BUILDS)
    parser.add_argument("--out", type=Path, default=REPO / "graal-native/out/renaissance-run")
    parser.add_argument("--benchmarks", default="")
    parser.add_argument("--configs", default=",".join(CONFIGS))
    parser.add_argument("--rounds", default="1,2,3")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--first-repeat", type=int, default=1, help="number of the first repeat (to run a disturbed process again under a number of its own)")
    parser.add_argument("--cpus", default="4-7")
    parser.add_argument("--heap", default="8g")
    parser.add_argument("--iterations", type=int, default=0, help="instead of the number mx runs (for a trial)")
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args()

    names = [b for b in ITERATIONS if not args.benchmarks or b in args.benchmarks.split(",")]
    scratch = args.out / time.strftime("%Y%m%dT%H%M%S")
    scratch.mkdir(parents=True)
    print(f"{time.strftime('%F %T')} host {os.uname().nodename}, load {os.getloadavg()}, results in {scratch}", flush=True)
    results_file = scratch / "results.jsonl"
    for benchmark in names:
        for repeat in range(args.first_repeat, args.first_repeat + args.repeats):
            for round_ in (int(r) for r in args.rounds.split(",")):
                for config in args.configs.split(","):
                    image = args.builds / f"{benchmark}-r{round_}" / config / "image"
                    r = run_once(benchmark, config, round_, repeat, image, args, scratch)
                    with results_file.open("a") as f:
                        f.write(json.dumps(r) + "\n")
                    mean_tail = sum(r["times_ms"][-6:]) / max(1, len(r["times_ms"][-6:])) if r.get("times_ms") else None
                    print(f"{time.strftime('%T')} {benchmark} {config} r{round_} #{repeat}: {r['status']}, exit {r.get('exit')}, {len(r.get('times_ms', []))} iterations, "
                          f"wall {r.get('wall_s')} s" + (f", last 6 mean {mean_tail:.1f} ms" if mean_tail else ""), flush=True)
    (scratch / "DONE").write_text(time.strftime("%F %T") + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
