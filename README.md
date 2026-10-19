# explicit-effects

A prototype side-effect analysis for Java programs compiled by Graal.
It translates Graal IR into a Static Single Use form in which every part of the heap is an explicit value, a *token*, that a method has to take and give back.
Which memory a call may change is then visible in its type, and load forwarding and dead-store removal become simple local rewrites.

If you are new to the problem, these two posts are the gentlest introduction:

- [Side-effect analysis](https://samuel-malec.github.io/blog/2026/08/17/side-effect-analysis/intro)
- [Graal's memory model](https://samuel-malec.github.io/blog/2026/09/27/graal-memory/intro)

## Repository Structure

```
explicit-effects/
├── src/
│   ├── graal/         # loads a Graal IR export
│   ├── cthu/          # the Graal dialect of Cthulhu, parser and single-use checker
│   ├── effects/       # heap partitions and method signatures: which partitions a method may touch
│   ├── graal2ct/      # the Graal IR → Cthulhu translation
│   └── rules/         # rewrites on the token form and the comparison with Graal
├── test/              # example exports and the checks
├── graal-export/      # runs the standalone points-to analysis and exports its facts and Graal IR
│   ├── examples/      # concept programs to learn the pipeline from
│   └── corpus/        # the programs the checks, make compare and the round trip are built from
├── graal-probe/       # measures what Graal itself does to the examples' loads and stores
├── graal-native/      # the round trip: native images built with the graal tree's side-effect analysis
├── programs/          # whole programs: Are We Fast Yet and the native-image driver
├── graal/             # submodule: our Graal fork with the exporter and the analysis feature
├── are-we-fast-yet/   # submodule: the Are We Fast Yet benchmarks
└── thesis/            # the thesis text
```

`src/effects/`, `src/rules/` and `programs/` each have their own README with the details and the results.

## Setup

The Python side is a [uv](https://docs.astral.sh/uv/) project with no runtime dependencies.
`uv sync` creates `.venv/` with the packages under `src/` and pytest. After that, `uv run` works from anywhere in the repository.

The Graal tree lives in the `graal/` submodule: the `side-effect-analysis` branch of [samuel-malec/graal](https://github.com/samuel-malec/graal).
Clone with `git clone --recurse-submodules`, or run `git submodule update --init` if you already cloned. Then build it like any other Graal tree:

```bash
cd graal/substratevm && JAVA_HOME=~/.mx/jdks/labsjdk-ce-latest-jvmci-25.4-b23_amd64 mx build
```

Once the submodule is built, the scripts use it. Until then, or whenever `GRAAL_HOME` is set, they use that tree instead.

## Learning the pipeline

[`graal-export/examples/`](graal-export/examples/) contains small self-contained programs, where 
each example's comment says what to look for. `make suite` exports them all and checks that each still shows what its comment says.

## Trying it out

Export the examples, translate one method, then run the rules on all of them:

```bash
cd graal-export && ./build.sh corpus/Examples.java && \
    DUMP_IR=out/examples.json ./run-dump.sh Examples && cd ..
uv run graal2ct graal-export/out/examples.json --method forwardAcrossWritingCall
uv run graal2ct graal-export/out/examples.json --partition field
uv run graal2ct graal-export/out/examples.json --partition field --rules
uv run graal2ct graal-export/out/aliasing.allocsens.json --partition object-field --rules
uv run pytest
./graal-probe/run.sh
```

`--partition` decides how finely the heap is split into tokens:

- `none`: one heap token
- `field`: one token per field (and per array kind)
- `object`: one per set of objects the points-to analysis can tell apart
- `object-field`: one per field of each such set

The last two read `<name>.allocsens.json`, which is exported with allocation sites.

## The Makefile

You rarely need to run the steps above by hand:

| Target | What it does |
| --- | --- |
| `make` | Re-exports `Examples` and `Signatures` if their source or the exporter changed, copies them to `test/data/` and runs the checks. |
| `make export` | Exports every example to `graal-export/out/<name>.json`, with the analysis report in `<name>.txt`. |
| `make translate` | Translates every export to `<name>.ct` with one heap token. Add `PARTITION=field` (or `object`, `object-field`) for `<name>.field.ct` and so on. |
| `make compare` | For each method of `Examples`, `Signatures` and `Aliasing`, shows the field loads and stores Graal leaves (from `graal-probe`) next to those our rules leave under each partitioning. |
| `make native` | Builds each example as a native image four times and checks each against the JVM. See below. |
| `make awfy`, `make driver` | Run the export and the rules on whole programs (`programs/README.md`). |
| `make native-awfy` | The timed round trip on Are We Fast Yet. |
| `make suite` | Exports the example suite, one program per example, and checks that each still shows what its comment says. |

The four images `make native` builds are:

1. as Graal compiles it;
2. with each call narrowed to what our tool says the callee may write;
3. additionally with each field access placed in its partition of the objects;
4. additionally with the stores our rules find dead in Java removed.

After `make native`, `make compare` shows the images too.
This needs the graal tree built with `mx build` in its `substratevm`: its image builder carries the side-effect analysis (`-H:+SideEffectAnalysis`), its compiler the kill sets on invokes and the partitions on field locations.

After rebuilding the Graal tree, force fresh exports with `make -B`.
