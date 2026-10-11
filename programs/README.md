# Real programs

The examples show what the token form and the round trip can do on code
written to show it. This directory runs them on whole programs, to see how
much of that survives contact with code nobody wrote for it.

- **[Are We Fast Yet](https://github.com/smarr/are-we-fast-yet)** (the
  `are-we-fast-yet` submodule, pinned at 74306fe): fourteen benchmarks over a
  small collection library of their own, so the JDK stays out of most of the
  code. [`awfy/Awfy.java`](awfy/Awfy.java) runs them all. The suite's harness
  picks a benchmark by name, through reflection, which hides the benchmarks
  from a closed-world analysis, so the driver constructs each one directly. It
  prints whether each verified to standard output and the run times to
  standard error, so a native image's output compares exactly with the JVM's.

- **The native-image driver** (`com.oracle.svm.driver`), from the graal tree:
  a real program of 449 methods, for scale. It is analysed only, not built
  as an image.

```bash
make awfy          # export both ways, then what the translation and the rules make of it
make native-awfy   # the round trip's four images, built both ways, and timed
make awfy-layouts  # why the narrowed images ran slower: counters across placements of the code
make driver        # the driver: exported both ways, and the same report
```

## What the export sees

The standalone analyzer has no implementation of any native method, and with
its predicates on it takes a call to one for a call that never returns. It
then drops everything after it. The driver calls `System.nanoTime()` before
the first benchmark, so with the default analysis 18 of the program's methods
are reachable. Without predicates (`-H:-UsePredicates`) there are 379, in 9 s.
With allocation sites, which turn predicates off too, there are the same 379
in 35 s.

The old repository found the same with lambdas: a call on an object that
came from a lambda never returns either. Without predicates, the analysis
also prunes less dead code. So these numbers don't compare with the
examples', which were exported with predicates on.

## What the translation and the rules make of it

`make awfy` (`rules.report`):

- **203 of the 379 methods translate.** The others are refused for:

  | Reason | Methods |
  |---|---|
  | allocation after escape analysis | 54 |
  | a constant other than an int or null (a `double`, a string, a class) | 47 |
  | an array element access | 33 |
  | `instanceof` | 13 |
  | a call with several targets, or an allocated array (`VirtualArray`, `NewArray`) | 6 each |
  | a narrowing conversion | 5 |
  | other node kinds | 6 |

- **147 of them (39%) touch everything.** The most common effects the
  standalone analyzer can't see through:

  | Effect | Methods |
  |---|---|
  | `Object.getClass()`, a native without facts | 57 |
  | a call through a functional interface whose lambdas it can't resolve, such as `som.ForEachInterface.apply` | 24 |
  | `Comparator.compare` | 18 |
  | `som.TestInterface.test` | 13 |
  | `MethodHandle.invokeBasic`, behind a lambda | 18 |
  | `richards.ProcessFunction.apply` | 4 |

- **The rules change almost nothing.** The translated methods hold 102 stores
  and 125 loads. The rules leave 102/122 per field, 102/124 with all of an
  object's fields together, and 102/122 per field of a set of objects. Java's
  dead stores and the trap model's are the same: none.

  The translated methods are what is left once the interesting ones are
  refused or opaque, mostly small accessors.

### Opacity is structural

The report names one effect per method, the first it finds, but most opaque
methods reach several. Giving `Object.getClass()` facts that touch nothing
leaves all 147 opaque. Even if every one of the 357 methods without facts,
natives and method handles alike, touched nothing, 137 would still touch
everything. The rest comes through calls the analysis can't resolve (through
functional interfaces, or `SoftReference.get`), through monitors, and through
array copies of an unknown kind.

## What the round trip makes of it

The round trip doesn't need the translation for its kills and partitions, and
it reads Native Image's own analysis, which knows `getClass` and lambdas.
`make native-awfy` builds the four images twice: once with Native Image's
default analysis for `graal` and `kills`, and once with allocation sites in
all four (`ALLOCSENS=1`), so that `objects` compares with images analysed the
same way. Every image prints what the JVM prints.

Field stores and loads Graal leaves in the suite's 388 compiled methods
(`rules.report --native`):

| Image | stores | in loops | loads | in loops | calls | narrowed calls (to nothing/one/several) |
|---|---|---|---|---|---|---|
| `graal` | 483 | 44 | 1047 | 159 | 1399 | |
| `kills` | 483 | 44 | **1004** | 154 | 1399 | 155/76/108 |
| `graal`, allocation sites | 484 | 44 | 1060 | 161 | 1102 | |
| `kills`, allocation sites | 484 | 44 | **1018** | 156 | 1102 | 155/76/108 |
| `objects` | 484 | 44 | 1018 | 156 | 1102 | 155/72/112 |
| `decisions` | 484 | 44 | 1018 | 156 | 1102 | 155/72/112 |

- **Kills remove 4% of the loads** (1047 to 1004, and 1060 to 1018 with
  allocation sites), five of them in loops.
- **Object partitions add nothing.**
  - The analysis does tell the suite's objects apart: 393 partitions over its
    240 fields.
  - But one method's accesses to a field almost always fall into a single
    partition. Of the 548 fields that get partitions in some method's graph,
    4 have two, all in CD's `voxelHash` (a constant vector against an
    allocated one).
  - So partitions separate almost nothing within a method, and across calls
    they removed no load either.
- **The decisions find no dead store**, as the rules find none either.
- **The two analyses compile differently.** With allocation sites, Native
  Image tracks no primitive values. It keeps three loops whose bounds the
  default analysis proved constant and unrolled completely: Havlak's
  `constructCFG` and `main`, and `Towers.buildTowerAt`. Those three methods
  have 298 fewer calls between them; the totals differ by 297. That is why
  `objects` is compared with the images analysed the same way.

## Run time

[`awfy/time.py`](awfy/time.py) runs every image five times, the images taking
turns. Each run measures each benchmark 20 times at the size the suite
benchmarks with, and drops the first iteration as warm-up. The table gives
the median of the rest, against `graal` (default analysis, and with
allocation sites in all four):

| Benchmark | `graal` ms | `kills` | `objects` | `decisions` | `graal` ms, alloc. sites | `kills` | `objects` | `decisions` |
|---|---|---|---|---|---|---|---|---|
| Bounce | 20.2 | −2.1% | −2.3% | −1.7% | 19.4 | +1.7% | +3.3% | +1.0% |
| CD | 41.6 | **+7.9%** | **+7.7%** | **+8.7%** | 42.1 | **+8.8%** | **+9.8%** | **+7.4%** |
| DeltaBlue | 16.3 | **+8.9%** | +3.2% | **+4.7%** | 17.0 | **+12.8%** | **+12.8%** | **−5.8%** |
| Havlak | 85.5 | −0.3% | **+4.1%** | +2.0% | 89.8 | −1.6% | −2.6% | −2.2% |
| Json | 53.5 | −0.4% | +1.3% | −0.2% | 54.9 | −1.2% | −1.7% | −0.7% |
| List | 68.9 | −0.7% | −0.9% | +0.3% | 68.3 | +1.4% | +0.7% | +1.3% |
| Mandelbrot | 42.2 | −0.1% | −0.0% | +0.1% | 42.4 | −0.2% | −0.2% | +0.0% |
| NBody | 11.8 | +0.2% | +0.5% | +0.7% | 12.0 | −0.8% | −0.5% | +0.1% |
| Permute | 25.3 | −0.3% | −2.0% | −0.9% | 25.1 | −0.5% | +0.1% | +0.5% |
| Queens | 20.7 | +0.6% | +0.8% | +1.9% | 20.8 | +1.2% | +1.6% | +1.1% |
| Richards | 75.8 | +2.6% | **+6.6%** | **+7.2%** | 76.8 | **+5.5%** | **+4.8%** | **+7.2%** |
| Sieve | 27.2 | +0.1% | −0.3% | +0.5% | 27.7 | −1.3% | −1.2% | −0.9% |
| Storage | 47.9 | −3.3% | **−4.7%** | −1.2% | 48.6 | **−5.0%** | **−5.3%** | −3.3% |
| Towers | 26.1 | +0.7% | +0.3% | +0.6% | 26.5 | −0.5% | −0.7% | −0.8% |
| **total** | 563.1 | +0.7% | +1.7% | +2.0% | 571.3 | +1.1% | +0.9% | +0.8% |

**The noise:** the same `graal` binary, timed twice the same way (an A/A
run), differs by at most 1.7% on a benchmark and 0.3% in total. Bold marks a
difference of more than twice that.

- **Fewer loads don't make the suite faster.** In total, every narrowed
  image is 1–2% slower than `graal`.
- **CD is 8–10% slower in every narrowed image, in both builds.** DeltaBlue is
  9–13% slower in the `kills` images, and Richards 5–7% slower in most narrowed
  images. Storage is 1–5% faster.
- **Where the kills changed CD and DeltaBlue, they removed loads.** In
  `BinaryConstraint.chooseMethod`, 14 loads drop to 9. In `Simulator.simulate`,
  9 drop to 6. In `RedBlackTree.remove`, 19 drop to 17.
- **DeltaBlue's numbers also move between images that differ only in
  partitions,** +3% against +13%, and so does its `decisions` image, −6%.
- **Step 6 found why** (next section). CD runs the same code in every image,
  placed 32 bytes further along, and the place costs the cycles. DeltaBlue's
  difference is noise in this way of timing.

## Why the narrowed images ran slower (step 6)

Step 5 timed CD 8–10% slower in every narrowed image, and DeltaBlue 9–13%
slower in the `kills` images. Two explanations were open:
- **Spills.** Native Image compiles a Java call with no callee-saved registers
  (`SubstrateAMD64RegisterConfig` lists none for normal calls). A value that
  lives across a call is stored to the stack before it and loaded back after
  it, and every load forwarded across a call makes one such value.
- **Placement.** The narrowing changes the code of some methods, and so their
  size, and every method placed after them moves.

Run times can't tell these apart; hardware counters can. Spills add
instructions, loads and stores, and placement changes none of them. So step 6
rebuilt `graal` and `kills` with the symbols `perf` needs, and counted.

```bash
make awfy-layouts   # every image below, then both tables
uv run python programs/awfy/counters.py CD graal-native/out/awfy-sym   # one benchmark's counters, per image
```

What that needed:
- `Awfy` takes a third argument, the one benchmark to run.
- `run.sh` takes `ONLY`, the images to build, `TAG`, a suffix for the output
  directory, and `EXTRA`, more `native-image` options. `-H:-DeleteLocalSymbols`
  keeps the methods' symbols, and `-H:CodeAlignment` sets where compiled
  methods may start.
- The feature takes `effects.only` and `effects.skip`: prefixes of the methods
  whose calls it narrows, or leaves alone.
- [`awfy/counters.py`](awfy/counters.py) runs images under `perf stat`, pinned to
  one CPU, the images taking turns; [`awfy/layouts.py`](awfy/layouts.py) sets
  `graal` against `kills` across alignments. The events are AMD Zen 4's: the
  numbers below are from a Ryzen 7 PRO 7840U.

### CD runs the same instructions, in more cycles

| CD, 20 iterations | cycles | instructions | loads | stores | op-cache misses |
|---|---|---|---|---|---|
| `graal` | 3.99 G | 14.81 G | 4.02 G | 1.81 G | 30 M |
| `kills` | **4.33 G** (+8.4%) | 14.76 G | 4.02 G | 1.82 G | 41 M |

`kills` takes 8% more cycles for the same instructions, loads and stores.
Spills would show in those counts, and they don't.

### Its hot methods are the same code, 32 bytes further along

The methods CD spends two thirds of its time in, `Vector2D.compareNumbers` and
both `compareTo`s, `CollisionDetector.isInVoxel`, `RedBlackTree.treeInsert`,
`put` and `findNode`, and `CallSign.compareTo`, compile to the same machine
code in both images. So do 56 of the 65 methods of CD's classes; the 9 that
differ take 9% of CD's time, and `RedBlackTree.remove`, one of them, none.

What differs is where they are. On AMD64, Native Image starts every method at a
multiple of 32 bytes. When a method grows past such a boundary, every method
after it moves by 32 bytes. In `kills`, methods placed before CD's hot ones
changed size, and three of the hot ones moved from the start of a 64-byte block
to its middle:

| Image | `Vector2D.compareNumbers` | `Vector2D.compareTo` | `RedBlackTree.treeInsert` | CD's cycles |
|---|---|---|---|---|
| `graal` | 0 | 0 | 0 | |
| `kills` | 32 | 32 | 32 | **+7.9%** |
| `kills`, CD's methods not narrowed | 0 | 0 | 0 | +0.2% |
| `kills`, only `RedBlackTree.remove` narrowed | 32 | 32 | 32 | **+7.4%** |
| `graal`, every method at a multiple of 64 bytes | 0 | 0 | 0 | −1.5% |
| `kills`, every method at a multiple of 64 bytes | 0 | 0 | 0 | −1.9% |

Offsets are within a 64-byte block, and cycles are against `graal`, all from
one run in which the images took turns.

Two controls pin it down:
- **CD's methods not narrowed** (`effects.skip=cd.`). Every other benchmark's
  calls are narrowed, but CD's code and offsets are `graal`'s, and so is its
  time.
- **Only `RedBlackTree.remove` narrowed** (`effects.only=cd.RedBlackTree.remove`).
  CD never runs it: the profile has no sample in it. Its narrowed calls make it
  four instructions longer, the methods after it move by 32 bytes, and CD runs
  7.4% slower.

Aligned to 64 bytes, `graal` and `kills` put CD's hot code at the same offsets,
and they run alike. So the narrowing slows CD down only by moving its code.
Which part of the processor's front end pays for the move, the counters don't
settle: op-cache misses rise by a third in `kills`, but not in the `remove`
image, which is as slow.

### DeltaBlue's slowdown was noise

Counted the same way, the rebuilt `graal` and `kills` take the same cycles on
DeltaBlue: 1.72 G each, ±1.3%. Timed the way step 5 timed it (`time.py`: wall
clock, every benchmark in one process, five processes per image), the same two
binaries gave DeltaBlue +13.0% in one run and +0.8% in the next, while CD gave
+9.5% and +8.8%. On this laptop the wall time of one process varies a lot: the
medians of eight DeltaBlue processes of one binary span 18.6 to 21.9 ms, even
pinned to one CPU. Step 5's A/A run, two series of one binary in one run, found
1.7%; repeated runs vary far more. Cycles, counted per process with the images
taking turns, vary by 1–2.5%.

### Placement alone moves run times as much

`layouts.py` builds on that. For each benchmark, it runs `graal` and `kills` with
methods aligned to 16, 32 (the default), 64 and 128 bytes, three runs each, the
images taking turns:

| Benchmark | `kills` against `graal`: 16 | 32 | 64 | 128 | mean | `graal` across alignments | instructions | loads | stores |
|---|---|---|---|---|---|---|---|---|---|
| Bounce | +0.2% | +0.7% | −3.4% | +1.4% | −0.3% | 6.0% | +0.05% | +0.04% | −0.01% |
| CD | −4.4% | **+9.4%** | −1.5% | +2.0% | +1.4% | **12.9%** | −0.20% | +0.23% | +0.48% |
| DeltaBlue | +3.6% | −2.9% | +1.9% | +1.0% | +0.9% | 6.0% | +0.12% | +0.22% | +0.69% |
| Havlak | +3.0% | −0.2% | −0.1% | −3.3% | −0.2% | 5.1% | −0.36% | −0.42% | −0.39% |
| Json | **−6.2%** | −0.0% | −0.1% | −0.9% | −1.8% | 7.5% | −0.39% | −1.37% | +2.10% |
| List | +0.6% | +0.3% | +0.1% | −1.5% | −0.1% | 6.4% | +0.00% | −0.01% | +0.01% |
| Mandelbrot | +0.0% | +0.0% | −0.0% | −0.0% | −0.0% | 0.8% | +0.01% | +0.01% | +0.01% |
| NBody | −0.3% | −0.4% | −0.3% | −0.0% | −0.3% | 0.4% | +0.11% | −0.05% | +0.03% |
| Permute | +1.4% | +2.3% | −0.8% | +0.5% | +0.9% | 9.2% | −0.04% | −0.08% | −0.03% |
| Queens | +3.9% | −0.4% | +1.8% | +4.5% | **+2.5%** | 4.4% | +0.75% | **+2.31%** | **+5.26%** |
| Richards | +0.2% | +2.1% | +4.8% | +3.3% | **+2.6%** | 6.3% | −2.03% | **+1.93%** | **+9.60%** |
| Sieve | −0.2% | −0.4% | +0.2% | +0.1% | −0.1% | 8.8% | −0.03% | +0.02% | +0.03% |
| Storage | −4.8% | +1.6% | +5.3% | +0.1% | +0.5% | **10.2%** | −0.02% | +0.05% | −0.10% |
| Towers | −0.9% | +0.8% | +0.4% | −1.0% | −0.2% | 3.8% | +0.02% | −0.14% | −0.13% |

"`graal` across alignments" is how far `graal`'s own cycles move between the
four builds, from the fastest to the slowest. The last three columns are
`kills` against `graal`, as the mean over the alignments.

- **Placement alone moves twelve of the fourteen benchmarks by 4–13%.** The
  four builds of `graal` have the same instructions in all 457 of the suite's
  methods, placed and padded differently. Only Mandelbrot and NBody, which
  spend their time in one small loop, stay within 1%. Counting one binary's
  cycles again varies by 1–2.5%, so placement is the larger noise.
- **For most benchmarks, `kills` against `graal` changes sign with the
  alignment:** CD from −4.4% to +9.4%, Storage from −4.8% to +5.3%. One timing
  of one pair of images, as in step 5, measures where their code landed.
- **Averaged over the alignments, `kills` is within 1% of `graal` on ten
  benchmarks.** CD (+1.4%) and Json (−1.8%) stay well within their spread.
  Queens (+2.5%) and Richards (+2.6%) are slower at three and at all four of
  the alignments.
- **The counts don't move with placement, and they show what the narrowing
  does.** Nowhere does it remove a noticeable share of the loads that run.
  Json runs 1.4% fewer loads, but 2.1% more stores. Queens and Richards run
  2% more loads and 5% and 10% more stores. The next section shows where those
  come from.

### Where the narrowing does change code, it trades loads for spills

The narrowing changes the instructions of 26 of the suite's 457 methods. Where
it does, it is because Graal now forwards a load across a call. The forwarded value has to survive the call, and with no
callee-saved registers it survives on the stack. That means a store before the
call and a load after it, where `graal` loads the field again after the call.

DeltaBlue's `BinaryConstraint.chooseMethod` calls
`v1.getWalkStrength().weaker(v2.getWalkStrength())` and then
`strength.stronger(v1.getWalkStrength())`. In `kills`, the call to `weaker`
kills nothing. So `graal` loads `strength`, `v1` and `v1.walkStrength` again
after that call, and `kills` keeps them on the stack across it:

```
graal, after the call to weaker:
    mov    0x10(%rsp),%rdi          ; this, from the stack
    mov    0x4(%rdi),%ecx           ; this.strength
    test   %eax,%eax
    je     …
    mov    0x8(%rdi),%esi           ; this.v1
    …
    mov    0xc(%r14,%rsi,8),%esi    ; v1.walkStrength
    mov    %rdx,%rdi
    call   Strength.stronger
```

```
kills, around the call to weaker:
    mov    %rbp,0x28(%rsp)          ; strength, to the stack
    mov    %edx,0x1c(%rsp)          ; strength, compressed, to the stack
    …
    mov    %rcx,0x10(%rsp)          ; v2.walkStrength, to the stack
    mov    %r8,0x20(%rsp)           ; v1.walkStrength, to the stack
    call   Strength.weaker
    test   %eax,%eax
    je     …
    mov    0x1c(%rsp),%edx          ; strength, compressed, from the stack
    …
    mov    0x28(%rsp),%rdi          ; strength, from the stack
    mov    0x20(%rsp),%rsi          ; v1.walkStrength, from the stack
    call   Strength.stronger
```

Two of the 26, counted in `objdump`'s output (moves only):

| Method | Image | instructions | stack stores | stack loads | other loads | frame |
|---|---|---|---|---|---|---|
| DeltaBlue's `BinaryConstraint.chooseMethod` | `graal` | 215 | 1 | 9 | 17 | 24 bytes |
| | `kills` | 220 | 8 | 18 | 12 | 56 bytes |
| Richards' `Scheduler.schedule` | `graal` | 135 | 2 | 5 | 11 | 24 bytes |
| | `kills` | 145 | 4 | 10 | 9 | 40 bytes |

`Scheduler.schedule` is Richards' main loop, and the only method of Richards
whose code the narrowing changes. In `kills` its call to
`isTaskHoldingOrWaiting()` kills nothing, so the loop keeps `currentTask` on
the stack across the call instead of loading the field again. That is where
Richards' extra stores come from, and why it is the one benchmark slower at
every alignment.

On Native Image, then, a load forwarded across a call saves nothing by itself.
The value comes back from the stack instead of from the object, and it costs a
store before the call.

## The native-image driver

`make driver` exports the driver's own package (`DUMP_FILTER=com.oracle.svm.driver`)
without predicates, and with allocation sites, in 14 and 54 s.

- **The class path from the old repository no longer suffices.** In this graal
  tree the driver also needs the builder's jar, `svm.jar`, for `ExitStatus`
  and `NativeImageGeneratorRunner`. Without it the analysis reaches 17 of the
  driver's methods. With it, 449, among 20,182 reachable methods.
- **134 of the 449 translate (30%).** The others are refused mostly for a
  constant other than an int or null (156), since the driver handles strings
  throughout. Then come allocation after escape analysis (48), array accesses
  (32), `instanceof` (28) and allocated arrays (19).
- **362 of them (81%) touch everything.** 244 are attributed to
  `Object.getClass()`, the rest to method handles behind lambdas and to
  `Unsafe`. As in Are We Fast Yet, the opacity is structural. If every one of
  the 420 methods without facts touched nothing, 325 would still touch
  everything: 217 through `SoftReference.get`, which the analysis can't
  resolve, and 46 through a monitor.
- **The rules change nothing:** 48 stores and 91 loads in the translated
  methods, under every partitioning.

## What step 5 says

On whole programs, the export and the token form reach little:
- the translation refuses about half of the methods (46% of Are We Fast Yet's,
  70% of the driver's);
- the standalone analysis leaves 39% and 81% of them touching everything,
  through effects that summaries of natives wouldn't remove;
- the rules remove 3 of 227 accesses in the one program and none in the other.

The round trip does better, because it reads Native Image's own analysis and
lets Graal optimize:
- narrowed calls remove 4% of Are We Fast Yet's loads;
- object partitions and dead stores add nothing there;
- the run time doesn't improve. Step 6 found that CD's 8–10% comes from where
  its code landed, and DeltaBlue's from noise in the timing; what the narrowing
  itself adds is spills.

What would move these numbers, in order of what they block:
1. **Translation gaps:** constants other than ints, allocation after escape
   analysis, and arrays.
2. **The facts for monitors and array copies,** which are opaque by design
   today.
3. **Why fewer loads ran slower:** answered by step 6, below. It was
   placement, plus spills where the code did change.

## What step 6 says

- **The slowdowns step 5 timed were not the narrowing's.** CD runs the same
  code in every image; the narrowing moved it by 32 bytes, and the move costs
  8% of its cycles. Narrowing only a method CD never runs costs the same, and
  not narrowing CD's methods costs nothing. DeltaBlue's difference was noise.
- **Placement alone moves twelve of the fourteen benchmarks by 4–13%,** and on
  this laptop the wall time of one process varies by up to a fifth. So one
  build of each image, timed, can't show a difference of a few percent. A
  comparison needs cycles counted per process, with the images taking turns,
  over several placements of each image, as `layouts.py` does, and the counts
  of instructions, loads and stores, which placement doesn't move.
- **What the narrowing itself does is add spills.** A Java call in Native
  Image preserves no register, so a load forwarded across a call becomes a
  store and a load on the stack. Richards and Queens run 10% and 5% more stores, and
  2.5% more cycles over all placements. Nowhere does the narrowing remove a
  noticeable share of the loads that run.
- **So narrowing more calls (step 7) won't make code faster by itself.**
  Forwarding pays where it enables more than the load: a load hoisted out of a
  loop, a check or branch folded, a dead store removed. That is what to count
  in step 7, along with the precision of the kills.

## Precise kill sets (step 7)

Step 7 made the kill sets as precise as the facts allow. It fixed the export,
took effects from what Graal says each node does, listed the platform's
fields by name, and made a narrowed call also kill what a safepoint may change
([`graal-native/README.md`](../graal-native/README.md#precise-kill-sets-step-7)).
`make awfy-layouts` builds and measures the images with the current kill sets.

| Are We Fast Yet | step 5 | step 7 |
|---|---|---|
| calls in the program's analysis graphs narrowed | 344 of 931 (37%) | **476 (51%)** |
| calls in the compiled code narrowed: to nothing/one/several | 339 of 1,407: 155/76/108 | **470: 158/91/221** |
| loads Graal leaves, of 1,063 without kills (in loops, of 167) | 1,020 (162) | **1,009 (161)** |
| stores Graal leaves, of 483 | 483 | 484 |

These images were built from step 6's `Awfy`, which takes a benchmark to run,
so `graal` leaves 1,063 loads here, not step 5's 1,047.

### What still makes a call kill everything

The first effect each still-`any` call reaches, among the 931:

| Effect | Calls | Mostly through |
|---|---|---|
| a lock | 333 | `Throwable.fillInStackTrace` (294), building an exception |
| run-time class initialization | 108 | DeltaBlue's `Strength` lambdas (65) and `Variable.<init>` (14) |
| an identity hash code, set by an atomic update | 10 | `WeakIdentityHashMap$Entry.hashCode` |
| an unresolved call, or a callee without facts | 4 | |

The blockers are layered. The lock in `fillInStackTrace` is on the exception
being built, which no other thread can see yet, so it is no effect at all. But
treating it as none exposes Native Image's monitor runtime behind 290 of those
calls, a volatile read in `JavaMonitor.isLocked`, and behind volatile reads
lies class initialization. What is left is synchronization and class
initialization:
- a lock or a volatile read lets this thread see what other threads wrote;
- class initialization runs code, under a lock, the first time a class is used.

A list of locations can't say either. Treating them needs to know which
locations other threads may write, and which objects another thread can see.
That is thread-escape analysis.

### What the code gains

Only 7 methods load less than with step 5's kills. Three loads each go in
CollisionDetector's frame lambda and in `HavlakLoopFinder.doDFS`. In `doDFS`,
step 5 had the calls to `Dictionary.atPut` and to `doDFS` itself kill
everything, because `atPut` allocates an entry. Step 7 has them kill the
dictionary's fields, the arrays and the union-find node's fields. So the
loads of `this.number` around them are forwarded, and the one in the loop
leaves the loop.

`layouts.py` again, on `graal` and step 7's `kills`:

| Benchmark | `kills` against `graal`: 16 | 32 | 64 | 128 | mean | `graal` across alignments | instructions | loads | stores |
|---|---|---|---|---|---|---|---|---|---|
| Bounce | +2.5% | +2.5% | −2.7% | −0.1% | +0.5% | 5.6% | −0.05% | −0.01% | +0.01% |
| CD | +0.6% | **+6.9%** | −1.7% | −1.1% | +1.2% | 7.6% | −0.33% | +0.16% | +0.53% |
| DeltaBlue | **−7.7%** | −2.3% | **+4.8%** | −0.3% | −1.4% | **18.4%** | +0.04% | −0.06% | +0.96% |
| Havlak | +1.6% | −0.7% | **−6.3%** | −0.4% | −1.4% | **10.4%** | −0.21% | +0.04% | +0.78% |
| Json | +1.0% | +1.1% | +0.5% | −1.2% | +0.4% | 0.9% | −0.36% | −1.15% | +2.27% |
| List | −0.1% | +0.2% | −0.1% | −0.8% | −0.2% | 6.1% | −0.00% | +0.03% | +0.02% |
| Mandelbrot | −0.0% | +0.0% | −0.0% | −0.0% | −0.0% | 0.7% | −0.00% | +0.04% | +0.02% |
| NBody | −0.6% | −0.3% | −0.3% | −0.2% | −0.4% | 0.2% | −0.03% | +0.02% | −0.03% |
| Permute | +2.7% | −0.1% | −0.0% | −0.7% | +0.5% | 9.1% | +0.00% | −0.06% | −0.07% |
| Queens | +0.6% | −0.6% | +0.0% | +4.4% | +1.1% | 6.7% | +0.75% | **+2.09%** | **+5.00%** |
| Richards | −4.1% | +5.3% | +5.5% | +4.9% | **+2.9%** | **10.8%** | −2.04% | **+1.39%** | **+9.36%** |
| Sieve | −0.6% | −0.3% | −0.1% | +0.0% | −0.2% | 9.8% | −0.05% | −0.02% | +0.01% |
| Storage | +2.3% | −2.3% | +0.3% | −0.2% | +0.0% | 2.3% | +0.06% | −0.25% | −0.09% |
| Towers | +0.1% | +0.0% | −0.6% | +0.6% | +0.1% | 3.7% | −0.05% | +0.27% | +0.20% |

- **No benchmark runs faster by more than placement alone moves it.** DeltaBlue's
  spread across alignments was 18% in this run against 6% in step 6's, so even
  the spread is noisy.
- **Richards and Queens again run more stores,** 9% and 5%: step 6's spills.
  Richards is slower at three of the four alignments.
- **Havlak, where step 7 forwards the most, now runs 0.8% more stores than
  `graal`,** where with step 5's kills it ran 0.4% fewer. `doDFS` keeps
  `this.number` across the calls it no longer reloads after, and so on the
  stack.

## What step 7 says

- **The facts were less precise than they could be.** One export bug and effects
  the exporter didn't ask Graal about made calls kill everything. Fixed, half
  the program's calls are narrowed instead of a third.
- **A narrowed call must also kill what a safepoint may change.** Native Image
  lowers allocation after its memory graph is built, and a collection resets
  the thread's allocation buffer. Steps 2–5 were safe only because a callee
  that allocated killed everything. Today's phases don't exploit the gap, so
  no control could show it.
- **What still makes a call kill everything is synchronization and class
  initialization.** They are layered behind each other, and treating them
  needs thread-escape analysis.
- **More precise kill sets don't make the code faster.** 131 more narrowed calls
  remove 11 more loads, and what they forward costs stores on the stack. As
  step 6 found, forwarding across a call pays only where it enables more, such
  as `doDFS`'s load leaving its loop, and that is rare here.

## The token side on real programs (step 8)

Steps 5 to 7 compared Graal with and without our facts. The token form, where
our rules run, saw little of Are We Fast Yet: the translation refused half of
its methods, and the ones it took were mostly accessors. Step 8 closed the gaps,
so that the rules run on the program's own methods, and Graal and the token
form can be compared on the same code with the same facts.

What it took ([`../src/graal2ct/README.md`](../src/graal2ct/README.md) lists
what each node becomes):
- **The graph exporter's twin of step 7's bug.** It too looked a call's flow up
  by the call's own bytecode index, so calls inlined before the analysis lost
  their targets, and the translation gave them every token.
- **More in the export.** The class an `instanceof` checks, an array access's
  element kind, the class and fields of an object escape analysis left
  virtual, what its commit sets them to, and which object a constant is.
- **More in the translation.**
  - allocations escape analysis made: `new_k` for each object, then `init_k`
    for each field;
  - arrays, on their kind's token;
  - calls with several targets: a dispatch that takes every target's tokens;
  - constants of any kind, conversions and math;
  - memory intrinsics and class initialization: calls that take every token
    of the method.

| Methods translated | before | after |
|---|---|---|
| Are We Fast Yet, the native image's export | 192 of 459 | **455** |
| Are We Fast Yet, the standalone export | 203 of 379 | **370** |
| the native-image driver, standalone | 134 of 449 | **427** |

Every translated method passes the single-use and type checks before and
after the rules, under every partitioning. In the examples, the one method the
translation refused, `forwardAcrossVirtualCall`, now translates, and the rules
forward its load as Graal does with the kill sets: over Examples and
Signatures, the rules leave 52/27 of 39 methods' accesses where Graal leaves
65/46. What is still refused is four
`switch`es in Are We Fast Yet, and in the driver also nine caught exceptions
and a value the export gives no type.

### What the rules do with them

- **Loads.** With a token per field, the rules forward 30 loads in Are We Fast
  Yet and 27 in the driver. With all of an object's fields in one partition,
  16; per field of a set of objects, 30 again, as on the examples.
- **Stores.** One store is dead in Java: in `JsonPureStringParser.endCapture`,
  `captureBuffer += …` is overwritten by `captureBuffer = ""`. Graal's own
  folding before the analysis took away the read between them, and nothing
  else in between can throw. The `decisions` image removes it, but Graal
  removes it in the `objects` image too: without the read, the two writes are
  adjacent.

### Graal and the token form side by side

`uv run python -m rules.report graal-native/out/awfy-s8/kills/export.json
graal-native/out/awfy-s8o/objects/export.json --side graal-native/out/awfy-s8
graal-native/out/awfy-s8o` sets the token form next to the images, method by
method. It covers the 384 methods that both translate and are compiled in
every image:

| Field stores/loads | export | our rules, per field | our rules, objects | `graal` | `kills` | `objects` | `decisions` |
|---|---|---|---|---|---|---|---|
| all | 386/734 | 385/**706** | 385/706 | 438/886 | 439/**839** | 440/851 | 440/851 |
| in loops | 45/182 | 45/173 | 45/173 | 44/167 | 44/161 | 44/163 | 44/163 |

- **The images start from more.** Native Image's peeling and duplication copy
  accesses after the analysis, as on the examples.
- **Graal does more with the same facts.** Our rules remove 28 of the export's
  734 loads (3.8%); Graal, given the kill sets, removes 47 of its 886 (5.3%).
- **Method by method,** Graal removes more loads than our rules in 12 methods,
  and our rules more in one, `RedBlackTree.put`. The rules take it from 26
  loads to 18, where Graal leaves 31 of 31. They forward the repeated loads of
  `x.parent` in the fix-up loop across the stores to `Node.color` in between,
  which a token per field keeps apart.
- **Where Graal does more,** the loads lie across branches, merges and loops in
  shapes the rules don't handle (see "What they don't do yet" in
  [`../src/rules/README.md`](../src/rules/README.md)):
  - `BinaryConstraint.chooseMethod`: 17 to 15 for the rules, 14 to 9 for Graal;
  - `Vector.sort`: 8 to 5, against 7 to 1;
  - `HavlakLoopFinder.doDFS`: 5 to 5, against 8 to 6.

## What step 8 says

- **The translation covers real programs now:** 99% of Are We Fast Yet's
  methods and 95% of the driver's, every one of them valid.
- **Given the same facts, Graal's phases remove more than our rules.** Its read
  elimination and floating reads are general, while the rules are a small set
  of local rewrites. They do better in only one method of the suite.
- **What only the token form decides, dead stores across calls,** finds one
  store legal in Java in the whole suite, and Graal removes that one anyway.
- **So on real programs, the token form counts through its signatures,** which
  tokens each method takes. Given to Graal as kill sets, they let Graal
  forward; the rules that rewrite the token form add little to that.
