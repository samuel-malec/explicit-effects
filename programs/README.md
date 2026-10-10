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
- **We haven't found why fewer loads run slower.** One candidate: a load
  forwarded across a call keeps its value alive through the call, so it may be
  spilled to the stack where a cheap reload from a cached field was before.
- **DeltaBlue's numbers also move between images that differ only in
  partitions,** +3% against +13%, and so does its `decisions` image, −6%.
  Code layout may account for part of what is left.

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
- the run time doesn't improve. CD and DeltaBlue run 8–13% slower, beyond the
  noise, for reasons not yet known.

What would move these numbers, in order of what they block:
1. **Translation gaps:** constants other than ints, allocation after escape
   analysis, and arrays.
2. **The facts for monitors and array copies,** which are opaque by design
   today.
3. **Why fewer loads ran slower.**
