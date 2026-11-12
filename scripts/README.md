# Helper scripts

Everything here drives or measures the tool: nothing in `src/`, `graal-export/`, `graal-native/` or the `Makefile` uses these files, so the analysis can be read and run without them.
They use the pipeline: each sources `graal-native/env.sh` (or `graal-export/env.sh`), which sets `SCRIPTS` to this directory, and builds through `graal-native/run.sh`.
Their output stays in `graal-native/out/`.

Run them from anywhere, for example `scripts/sharing/thread-escape.sh`. The numbers in the thesis come from `evaluation/`, on pontos04 only.

## `evaluation/`: the numbers of the evaluation chapter

| Script | What it does |
| --- | --- |
| `reproduce.sh` | Regenerates the headline tables from one commit; refuses a tree that is not exactly a commit. Calls the others here. |
| `awfy-repeat.sh` | AWFY's `graal` and `fields` built several times and timed together, because builds differ more than runs. |
| `counts.py` | Loads, loads in loops, stores and calls Graal leaves in each image. |
| `control_flow.py` | Blocks, control-flow edges, ifs and loops two images leave, and the loads that left a loop. |
| `load_split.py` | The loads of a designed program split into its controls, the methods that do not change, and the methods that lose loads. |
| `cost.sh`, `cost.py` | What the analysis adds to a build, per configuration, and the table. |
| `cost-javac.sh` | The same on javac. |
| `time_locks.sh` | What removing locks and volatile accesses is worth on the designed shapes. |
| `time_javac.py` | How long each javac image takes to compile AWFY. |
| `image_sizes.py` | The size of the images of `graal` and `fields` from the build logs: the file, the code area, the image heap. |
| `scaling.py` | What `fields` adds to a build against the size of the image, over the programs the logs hold; the fit and a figure. |
| `footprint.py` | What adopting the feature costs: the fork's change to Graal against upstream, the options, the tool's size. |
| `barista_compare.py` | Whether the Barista images that `barista_run.py` started answered alike. |

## `frameworks/`: real servers

| Script | What it does |
| --- | --- |
| `bundle.sh` | Applies a Native Image bundle in one configuration, or without the feature (`build_plain`, the control); sourced by the scripts below. |
| `petclinic.sh`, `petclinic_load.py` | Spring PetClinic's builds, and the images under load. |
| `petclinic/` | The four reflection registrations the 2023 bundle lacks, and how they were found. |
| `barista.sh` | An application of the Barista suite, one image per configuration. |
| `barista-gate.sh` | The gate before a load run: four configurations of an application, and why no site is removable. |
| `barista_run.py` | Starts every Barista image the builds left, sends it its workload's requests and keeps the answers (compare them with `evaluation/barista_compare.py`). |
| `barista-control.sh` | The same bundle with and without the feature, to tell whether an image that does not start is ours. |
| `tika-hang.sh` | The quarkus-tika bundle applied again and again with and without the feature: whether a hang of the build is the feature's. |

## `sharing/`: why thread escape answers what it answers

| Script | What it does |
| --- | --- |
| `thread-escape.sh`, `thread_escape.py` | The verdict on each `graal-export/examples/sharing` program, per analysis and assumption. |
| `explain-sharing.sh` | The chain of reasons an object is shared. |
| `why_no_locks.py` | What blocks each lock site in an export. |
| `publication-controls.sh` | Leaves out one kind of publishing site at a time; the examples it publishes must turn local. |

## `robustness/`: controls that must fail or hold

| Script | What it does |
| --- | --- |
| `deopt/deopt-locks.sh` | Lock removal against deoptimization, with a control that aborts. |
| `svm-test-locks.sh` | Native Image's own JUnit tests with lock elision on. |

## `server/`

| Script | What it does |
| --- | --- |
| `sync-pontos.sh` | Mirrors the tool and the fork to pontos04 and stamps both with their commit. |
