"""Spring PetClinic images under load: the pages they answer, how fast they start, and how many requests per second they serve.

Usage:
    uv run python scripts/frameworks/petclinic_load.py --image graal=out/petclinic/graal/image --image kills=out/petclinic/kills/image \\
        [--runs 5] [--seconds 30] [--warmup 15] [--clients 16]

Each run starts every image in turn as a fresh process (an empty in-memory database), pinned to the server's cores, fetches some
deterministic pages (their bodies must be the same in every image), warms it up and then loads it with wrk, which runs the
mixed workload of the Graal benchmark suite (workloads/mixed-requests.lua: creates an owner, a pet and a visit, and reads them
back) from other cores, with as many connections as wrk threads (the script keeps its state per thread, so one connection
each, as the suite's sizes do: 2, 4, 16, 32). The table gives, per image, the median requests per second over the runs with the range, the median
latency at the 50th and 99th percentile, the resident set after the load, the time to the first answer, and each image's
requests per second against the first image's. List the first image twice under two labels for the noise (A/A). The script
refuses to start while anything answers on port 8080 (a server left over would answer in place of the one it starts) and stops
if the server it started is not running when it answers.

The assets are in $PETCLINIC (default ~/eval/petclinic): wrk/wrk-linux-amd64 and workloads/.
"""

import argparse
import hashlib
import os
import re
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PAGES = ["/", "/vets.html", "/owners?lastName=", "/owners/1", "/owners/find", "/owners/3/pets/4/edit"]
UNIT = {"us": 1e-3, "ms": 1.0, "s": 1e3}


def get(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=10) as answer:
            return answer.status, answer.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def rss_mib(pid: int) -> float:
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024
    raise RuntimeError(f"process {pid} has no resident set: it is not running")


def one_run(image: Path, args: argparse.Namespace, assets: Path) -> dict:
    try:
        get("http://localhost:8080/")
    except OSError:
        pass
    else:  # a server left over from before would answer in place of the one started here
        raise RuntimeError("something already answers on port 8080; stop it first")
    start = time.perf_counter()
    server = subprocess.Popen(["taskset", "-c", args.server_cpus, str(image)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              cwd=image.parent)
    try:
        while True:
            if server.poll() is not None:
                raise RuntimeError(f"{image} stopped with {server.returncode}")
            try:
                if get("http://localhost:8080/")[0] == 200:
                    break
            except OSError:
                time.sleep(0.02)
            if time.perf_counter() - start > 60:
                raise RuntimeError(f"{image} did not answer in 60 s")
        first_answer = time.perf_counter() - start
        if server.poll() is not None:  # it answered, but not this process
            raise RuntimeError(f"{image} stopped with {server.returncode} while something else answered on port 8080")
        pages = {page: (status, hashlib.sha256(body).hexdigest()[:12]) for page in PAGES for status, body in [get("http://localhost:8080" + page)]}
        wrk = [str(assets / "wrk" / "wrk-linux-amd64"), "-t", str(args.clients), "-c", str(args.clients), "--latency",
               "-s", str(assets / "workloads" / "mixed-requests.lua"), "http://localhost:8080"]
        subprocess.run(["taskset", "-c", args.wrk_cpus, *wrk, "-d", f"{args.warmup}s"], capture_output=True, check=True, cwd=assets / "workloads")
        done = subprocess.run(["taskset", "-c", args.wrk_cpus, *wrk, "-d", f"{args.seconds}s"], capture_output=True, text=True, check=True,
                              cwd=assets / "workloads")
        text = done.stdout
        latency = {int(p): float(v) * UNIT[u] for p, v, u in re.findall(r"^\s+(\d+)%\s+([\d.]+)(us|ms|s)\s*$", text, re.M)}
        failed = re.search(r"Non-2xx or 3xx responses: (\d+)", text)
        return {"rps": float(re.search(r"Requests/sec:\s+([\d.]+)", text).group(1)), "p50": latency.get(50, float("nan")),
                "p99": latency.get(99, float("nan")), "rss": rss_mib(server.pid), "first": first_answer, "pages": pages,
                "failed": int(failed.group(1)) if failed else 0}
    finally:
        server.terminate()
        try:
            server.wait(10)
        except subprocess.TimeoutExpired:
            server.kill()
        time.sleep(1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--image", action="append", required=True, metavar="LABEL=PATH")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=15)
    parser.add_argument("--clients", type=int, default=16, help="wrk threads, one connection each (the suite's mixed-large)")
    parser.add_argument("--server-cpus", default="4-7")
    parser.add_argument("--wrk-cpus", default="8-11")
    args = parser.parse_args()
    assets = Path(os.environ.get("PETCLINIC", Path.home() / "eval/petclinic"))
    images = {label: Path(path).resolve() for label, _, path in (item.partition("=") for item in args.image)}

    results: dict[str, list[dict]] = {label: [] for label in images}
    for run in range(args.runs):
        for label, image in images.items():
            result = one_run(image, args, assets)
            results[label].append(result)
            print(f"run {run + 1} of {args.runs}, {label}: {result['rps']:.0f} requests/s, p99 {result['p99']:.1f} ms, {result['failed']} failed", file=sys.stderr)

    first = next(iter(images))
    base = statistics.median(r["rps"] for r in results[first])
    print(f"{args.clients} clients (wrk threads with one connection each), {args.seconds} s after {args.warmup} s warm-up, {args.runs} runs; server on cpus {args.server_cpus}, wrk on {args.wrk_cpus}")
    print(f"{'image':22} {'requests/s':>11} {'(min–max)':>17} {'vs ' + first:>14} {'p50 ms':>7} {'p99 ms':>7} {'RSS MiB':>8} {'first answer s':>15} {'failed':>7}")
    for label, runs in results.items():
        rps = [r["rps"] for r in runs]
        med = statistics.median(rps)
        print(f"{label:22} {med:>11.0f} {f'({min(rps):.0f}–{max(rps):.0f})':>17} {100 * (med / base - 1):>+13.1f}% "
              f"{statistics.median(r['p50'] for r in runs):>7.2f} {statistics.median(r['p99'] for r in runs):>7.2f} "
              f"{statistics.median(r['rss'] for r in runs):>8.0f} {statistics.median(r['first'] for r in runs):>15.3f} {sum(r['failed'] for r in runs):>7}")
    # the pages must be the same in every image
    reference = results[first][0]["pages"]
    differing = {label: [p for p, v in runs[0]["pages"].items() if v != reference[p]] for label, runs in results.items()}
    print("\npages (status, hash of the body) against the first image's:",
          "all equal" if not any(differing.values()) else {label: pages for label, pages in differing.items() if pages})
    print("statuses:", {p: v[0] for p, v in reference.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
