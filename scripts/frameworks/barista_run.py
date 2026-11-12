"""Start every Barista image the builds left (graal and fields, rounds 1-3), send each the requests of its workload, and compare the answers between the
images of one application. Run where the images are (pontos04); it reads the images, builds nothing, and stops every server it starts.

Usage:
    python3 scripts/frameworks/barista_run.py [--out DIR] [--apps a,b] [--rounds 1,2,3] [--cpus 4-7] [--builds DIR] [--configs graal,fields]
    python3 scripts/evaluation/barista_compare.py <the directory it prints>

The images are the ones of barista.sh (--builds, default graal-native/out/barista: <app>-r<k>/<config>/image, made with TAG=r<k>); the bundles' workloads
are in $BARISTA (default ~/eval/barista), as for barista.sh. An image counts as running when it answers its first request, and as right when every answer
(status code and a hash of the body) equals the answers of the other images of the application, `graal` against `graal` included (the control: bodies that
differ between two images of the same configuration are not ours). The images take turns (graal r1, fields r1, graal r2, ...), one at a time, pinned to
--cpus, each in its own scratch directory (dropwizard writes its H2 database into the working directory). Every answer's body is kept for barista_compare.py.
The time to the first answer and the resident set after the requests are recorded as seen, one start each; they are not a measurement.
"""

import argparse
import hashlib
import http.client
import json
import os
import signal
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ASSETS = Path(os.environ.get("BARISTA", Path.home() / "eval/barista"))

# the first request of a list is the one that tells the server is up
PETCLINIC_PAGES = ["/", "/vets.html", "/owners?lastName=", "/owners/1", "/owners/find", "/owners/3/pets/4/edit"]
SHOPCART_JSON = {"content-type": "application/json"}
# the configuration of Barista's dropwizard-hello-world (benchmarks/dropwizard-hello-world/minimal.yml of the suite): the bundle does not carry it
MINIMAL_YML = """template: Hello, %s!
defaultName: Stranger

database:
  driverClass: org.h2.Driver
  user: sa
  password: sa
  url: jdbc:h2:./target/example

server:
  applicationConnectors:
    - type: http
      port: 8012
  adminConnectors:
    - type: http
      port: 8082
  requestLog:
    appenders: []

logging:
  level: WARN
  loggers:
    com.example.helloworld: INFO
  appenders:
    - type: console

viewRendererConfiguration:
  freemarker:
    strict_syntax: true
"""


def hello(port: int, path: str, **extra) -> dict:
    return {"port": port, "requests": [("GET", path, None, {})] * 5, **extra}


def similarity_body() -> bytes:
    texts = [(ASSETS / "micronaut-similarity/workloads" / f"essay{i}.txt").read_text() for i in range(1, 17)]
    return json.dumps({"texts": texts}).encode()


def apps() -> dict[str, dict]:
    return {
        "vanilla-hello-world": hello(8010, "/hello"),
        "helidon-hello-world": hello(8007, "/hello"),
        "ktor-hello-world": hello(8008, "/"),
        "micronaut-hello-world": hello(8000, "/hello"),
        "play-scala-hello-world": hello(8009, "/", args=["-Dpidfile.path=/dev/null"]),
        "spring-hello-world": hello(8005, "/hello"),
        "vertx-hello-world": hello(8011, "/"),
        "dropwizard-hello-world": hello(8012, "/hello-world", args=["server", "minimal.yml"], files={"minimal.yml": MINIMAL_YML}),
        "micronaut-shopcart": {"port": 8001, "requests": [
            ("POST", "/", b'{"username": "1", "name": "1name"}', SHOPCART_JSON),
            ("POST", "/cart", b'{"username": "1", "name": "bananas", "amount": "7"}', SHOPCART_JSON),
            ("POST", "/cart", b'{"username": "1", "name": "joghurt", "amount": "12"}', SHOPCART_JSON),
            ("POST", "/cart", b'{"username": "1", "name": "coffee", "amount": "5"}', SHOPCART_JSON),
            ("POST", "/cart", b'{"username": "1", "name": "cheese", "amount": "5"}', SHOPCART_JSON),
            ("POST", "/cart", b'{"username": "1", "name": "meat", "amount": "800"}', SHOPCART_JSON),
            ("GET", "/cart/1", None, {}),
            ("DELETE", "/1", None, {}),
        ]},
        "micronaut-similarity": {"port": 8002, "requests": lambda: [("POST", "/similarity/order", similarity_body(), SHOPCART_JSON)]},
        "spring-petclinic": {"port": 8006, "requests": [("GET", page, None, {}) for page in PETCLINIC_PAGES]},
    }


def ask(port: int, method: str, path: str, body: bytes | None, headers: dict, timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            return answer.status, answer.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def answers_on(port: int) -> bool:
    try:
        ask(port, "GET", "/", None, {}, 2)
        return True
    except (OSError, http.client.HTTPException):
        return False


def rss_mib(pid: int) -> float | None:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return round(int(line.split()[1]) / 1024, 1)
    except OSError:
        return None


def provenance(directory: Path) -> str:
    path = directory / "provenance.txt"
    return " | ".join(l.strip() for l in path.read_text().splitlines()[:6]) if path.exists() else "no provenance.txt"


def run_image(app: str, spec: dict, builds: Path, config: str, round_: int, scratch: Path, cpus: str) -> dict:
    directory = builds / f"{app}-r{round_}" / config
    result = {"app": app, "config": config, "round": round_, "build": provenance(directory)}
    image = directory / "image"
    if not image.exists():
        return {**result, "status": "no image", "image": str(image)}
    image = image.resolve()
    result["image_bytes"] = image.stat().st_size
    work = scratch / f"{app}-{config}-r{round_}"
    work.mkdir(parents=True)
    for name, text in spec.get("files", {}).items():
        (work / name).write_text(text)
    if answers_on(spec["port"]):
        return {**result, "status": f"port {spec['port']} already answers"}
    requests = spec["requests"]() if callable(spec["requests"]) else spec["requests"]
    log = work / "output.log"
    started = time.monotonic()
    with log.open("wb") as out:
        process = subprocess.Popen(["taskset", "-c", cpus, str(image), *spec.get("args", [])], cwd=work, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        method, path, body, headers = requests[0]
        first = None
        while time.monotonic() - started < 90:
            if process.poll() is not None:
                return {**result, "status": f"exited with {process.returncode} before answering", "log": str(log)}
            try:
                first = ask(spec["port"], method, path, body, headers, 10)
                result["first_answer_s"] = round(time.monotonic() - started, 2)
                break
            except (OSError, http.client.HTTPException):
                time.sleep(0.05)
        if first is None:
            return {**result, "status": "no answer in 90 s", "log": str(log)}
        answers = []
        for i, (method, path, body, headers) in enumerate(requests):
            try:
                status, content = first if i == 0 else ask(spec["port"], method, path, body, headers, 30)
            except (OSError, http.client.HTTPException) as e:
                status, content = f"error {type(e).__name__}", b""
            (work / f"answer-{i}.body").write_bytes(content)
            answers.append({"request": f"{method} {path}", "status": status, "sha": hashlib.sha256(content).hexdigest()[:12], "bytes": len(content),
                            "text": content[:70].decode(errors="replace")})
        result["answers"] = answers
        result["rss_mib"] = rss_mib(process.pid)
        result["status"] = "answered"
    finally:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            result["exit"] = process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            result["exit"] = f"killed after 20 s ({process.wait()})"
    lines = log.read_text(errors="replace").splitlines()
    result["log"] = str(log)
    result["log_lines"] = len(lines)
    result["log_errors"] = [l[:160] for l in lines if "Exception" in l or "ERROR" in l or "SEVERE" in l][:3]
    return result


def verdict(results: list[dict]) -> str:
    started = [r for r in results if r["status"] == "answered"]
    if len(started) < len(results):
        return "NOT ALL STARTED: " + ", ".join(f"{r['config']}-r{r['round']}: {r['status']}" for r in results if r["status"] != "answered")
    groups: dict[str, list[str]] = {}
    for r in started:
        groups.setdefault(json.dumps([(a["status"], a["sha"]) for a in r["answers"]]), []).append(f"{r['config']}-r{r['round']}")
    return "identical answers in all " + str(len(started)) if len(groups) == 1 else "DIFFERENT: " + "; ".join(f"{members}" for members in groups.values())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=REPO / "graal-native/out/barista-run")
    parser.add_argument("--apps", default="")
    parser.add_argument("--rounds", default="1,2,3")
    parser.add_argument("--cpus", default="4-7")
    parser.add_argument("--builds", type=Path, default=REPO / "graal-native/out/barista")
    parser.add_argument("--configs", default="graal,fields")
    args = parser.parse_args()
    configs = args.configs.split(",")

    specs = apps()
    names = [a for a in specs if not args.apps or a in args.apps.split(",")]
    scratch = args.out / time.strftime("%Y%m%dT%H%M%S")
    scratch.mkdir(parents=True)
    print(f"{time.strftime('%F %T')} host {os.uname().nodename}, load {os.getloadavg()}, results in {scratch}", flush=True)
    for _ in range(24):
        if os.getloadavg()[0] < 1.0:
            break
        time.sleep(5)
    else:
        print("WARNING: the load average stayed above 1 for two minutes", flush=True)

    results: dict[str, list[dict]] = {}
    for app in names:
        results[app] = []
        for round_ in (int(r) for r in args.rounds.split(",")):
            for config in configs:
                r = run_image(app, specs[app], args.builds, config, round_, scratch, args.cpus)
                results[app].append(r)
                print(f"{time.strftime('%T')} {app} {config} r{round_}: {r['status']}" + (f", first answer {r['first_answer_s']} s, {[a['status'] for a in r['answers']]}, exit {r['exit']}" if r["status"] == "answered" else ""), flush=True)
    (scratch / "results.json").write_text(json.dumps(results, indent=1))

    lines = [f"{'application':26} {'images':>6}  verdict"]
    for app, rs in results.items():
        lines.append(f"{app:26} {len(rs):>6}  {verdict(rs)}")
    lines.append("")
    for app, rs in results.items():
        answered = [r for r in rs if r["status"] == "answered"]
        if answered:
            lines.append(f"{app}: " + "; ".join(f"{a['request']} -> {a['status']} {a['bytes']} B {a['sha']} {a['text']!r}" for a in answered[0]["answers"][:3]))
    (scratch / "SUMMARY.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines), flush=True)
    (scratch / "DONE").write_text(time.strftime("%F %T") + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
