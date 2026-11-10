"""Compare the answers of the Barista images that scripts/frameworks/barista_run.py started: per application, whether every image of it answered the
same, and the time to the first answer and the resident set as seen.

Usage:
    python3 scripts/evaluation/barista_compare.py <run directory> [<run directory> ...]

Reads results.json and the saved bodies (<app>-<config>-r<k>/answer-<i>.body) of each run directory. An image is right when its answers equal those of
every other image of its application, `graal` against `graal` included. Two fields change from one start to the next, between two images of the same
configuration as well, and are masked before comparing: micronaut-shopcart's `timestamp = <milliseconds>` and micronaut-similarity's `time`
(nanoseconds of the request). Everything else is compared byte for byte. Nothing is started here.
"""

import json
import re
import sys
from pathlib import Path

MASKED = ("micronaut-shopcart", "micronaut-similarity")


def normalised(app: str, body: bytes) -> bytes:
    if app == "micronaut-shopcart":
        return re.sub(rb"timestamp = \d+", b"timestamp = T", body)
    if app == "micronaut-similarity":
        data = json.loads(body)
        data.pop("time", None)
        return json.dumps(data, sort_keys=False).encode()
    return body


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    for directory in map(Path, sys.argv[1:]):
        results = json.loads((directory / "results.json").read_text())
        configs = list(dict.fromkeys(r["config"] for images in results.values() for r in images))
        print(f"== {directory.name}")
        print(f"{'application':24} {'started':>8} {'answers':>8} {'groups':>6}  verdict")
        for app, images in results.items():
            started = [r for r in images if r["status"] == "answered"]
            groups: dict[tuple, list[str]] = {}
            for r in started:
                work = directory / f"{app}-{r['config']}-r{r['round']}"
                key = tuple((a["status"], normalised(app, (work / f"answer-{i}.body").read_bytes())) for i, a in enumerate(r["answers"]))
                groups.setdefault(key, []).append(f"{r['config']}-r{r['round']}")
            requests = len(started[0]["answers"]) if started else 0
            if len(started) < len(images):
                verdict = "NOT STARTED: " + ", ".join(sorted({r["status"] for r in images if r["status"] != "answered"}))
            elif len(groups) == 1:
                verdict = "identical in all images" + (" (a masked field)" if app in MASKED else "")
            else:
                verdict = "DIFFERENT: " + "; ".join(",".join(g) for g in groups.values())
            print(f"{app:24} {len(started):>3}/{len(images):<4} {requests:>8} {len(groups):>6}  {verdict}")
            if started:
                print(f"{'':24} statuses {sorted({a['status'] for r in started for a in r['answers']})}, "
                      f"exit codes on SIGTERM {sorted({str(r.get('exit')) for r in started})}")
        print("as seen, one start of each image (not a measurement: cold files, no repeats): time to the first answer in seconds and resident set in MiB after")
        print("the requests, each configuration over its rounds (min-max)")
        print(f"{'application':24} " + " ".join(f"{c + ' first s':>16} {c + ' rss MiB':>16}" for c in configs))
        for app, images in results.items():
            cells = []
            for config in configs:
                for key in ("first_answer_s", "rss_mib"):
                    values = [r[key] for r in images if r["config"] == config and r["status"] == "answered" and r.get(key) is not None]
                    cells.append(f"{min(values):g}-{max(values):g}" if values else "-")
            print(f"{app:24} " + " ".join(f"{c:>16}" for c in cells))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
