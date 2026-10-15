# The example suite

Forty small programs, one concept each. Every class is a program of its own:

- **`demo`** is the one method to study.
- **A helper** appears only when the concept needs a callee. It is recursive, so that Graal can't inline it before the analysis.
- **`main`** only drives `demo`. It prints nothing, which keeps the analysis and the export small.

Each class is exported on its own, so the points-to analysis sees nothing but that example.

| Package | What it shows |
| --- | --- |
| [`conversion/`](conversion) | how Graal IR becomes the token form, one construct at a time |
| [`limits/`](limits) | what the translation refuses, and what makes a method touch everything |
| [`forwarding/`](forwarding) | loads the rules replace with a value they already know |
| [`deadstores/`](deadstores) | stores the rules remove, and what keeps a store alive |
| [`objects/`](objects) | what telling objects apart adds, with allocation sites |

Each optimization comes with a **control**: a variant where something real stops the rule. A name ending in `Blocks`, `Keeps` or `MaybeAlias` says what stops it. A rule that fires on its control is wrong.

## Setup

From the repository root:

```bash
make suite
```

This exports every example whose source changed to `graal-export/out/suite/<package>.<Class>.json`, which takes about a minute the first time. It also exports each `objects` example with allocation sites, as `<package>.<Class>.allocsens.json`. Then it runs [`check_suite.py`](../../test/export_check/check_suite.py), which checks that every example still shows what this guide says.

To export just one example, run `graal-export/suite.sh AcrossCall`.

## How to work through one example

Take `forwarding.AcrossCall`:

1. **Read the Java** and its comment. Predict what Graal does with it and what the token form should look like.
2. **Read Graal's IR,** the graph the export holds:
   ```bash
   uv run python -m graal.show graal-export/out/suite/forwarding.AcrossCall.json --method demo
   ```
   Blocks in order, each node as `id op type inputs details`, and where each block goes.
3. **Read the token form,** with one heap token first, then with a token per field:
   ```bash
   uv run graal2ct graal-export/out/suite/forwarding.AcrossCall.json --method demo --partition none
   ```
   ```bash
   uv run graal2ct graal-export/out/suite/forwarding.AcrossCall.json --method demo --partition field
   ```
   Match each Graal block to its λ (`b3` is block 3), and each memory node to its `get`/`set`. Add `--types` to see each λ's parameter types.
4. **Apply the rules** (optimization examples only). Add `--rules`. Stderr lists each load forwarded and each store removed. Compare `none` with `field`, and for `objects` compare `field` with `object-field` (see below).
5. **Explain the difference** to yourself in one sentence: which token chain made it possible, or which instruction blocked it.

## The order

Work through the parts in order. Within a part, each example builds on the one before.

### Part 1: conversion, from Graal IR to tokens

Use `--partition field`, unless the row says otherwise. Graal's blocks become λs.

| # | Example | Concept | What to look for |
| --- | --- | --- | --- |
| 1 | `PureArithmetic` | a λ, values only | `field`: no token at all. `none`: the method still takes `h` and gives back `hout` |
| 2 | `StaticFieldUpdate` | threading a token | `getstatic_0 h_total → … h_total1`, then `setstatic_0 h_total1 … → h_total2`: each memory operation takes one version and gives the next |
| 3 | `NullCheck` | a failed check is control flow | Graal: `IsNull`, `If`, a block with `BytecodeException`, `Unwind`. Tokens: a λ marked `throws` makes `ref exception`, and the unwind λ moves it to `exc` |
| 4 | `ReceiverField` | no check needed | the same load through `this`: one λ, no branch |
| 5 | `IfElse` | a branch | `opt`/`opt`/`join` pick an arm, the frame forks each token, and each arm passes the token it didn't touch straight on to the merge λ `b3` |
| 6 | `ValueMerge` | a phi | Graal's `ValuePhi` in block 3 is the merge λ's parameter, `b3 = λ v13`, and each arm passes `p0` or `p1` for it |
| 7 | `CountingLoop` | a loop | the header λ's parameters are the loop phis `i` and `sum`, and the body ends by jumping back to the header |
| 8 | `LoopOverField` | memory in a loop | `h_total` is a parameter of the header too: the token goes around the loop. Try `--rules`: the load is forwarded from the store of the iteration before |
| 9 | `StaticCall` | a call | `… bump run → k5`, `call k5 p0_2 h_count → v9 h_count1`: only the callee's token goes in. `v9` is its exception, which the caller branches on (`nil?`) |
| 10 | `PureCall` | a call that touches nothing | `f_i_ir call k3 p0`: no token. With `--partition none` the call takes `h` |
| 11 | `VirtualCall` | two possible targets | `dispatch_… run`, an external, "one of" both `grow`s: the call takes both implementations' tokens |
| 12 | `CatchException` | a handler | the handler λ takes the exception as its first parameter, tests its class (`instanceof_0`), and throws on anything else |
| 13 | `ThrowException` | throwing | the unwind λ: `ref move … → exc`, `int bot → r`, every token out |
| 14 | `NewObject` | an allocation after escape analysis | `new_0` on `h_rest`, then `init_0` and `init_1` (the fields' first values, zeros), then the constructor call |
| 15 | `ArrayElement` | arrays | `ref length`, a `throws` λ for each failed check (null, index out of bounds), `aget_int` and `aset_int` on `h_int_arr` |

The exception examples (12, 13) take every token. That isn't about exceptions: making the exception calls `Throwable.<init>`, which reaches a call the standalone analysis can't resolve (`limits.OpaqueCall` is the same thing on purpose).

**Questions after part 1:**
- Why does a λ take every token of its method, even one it never touches?
- What exactly does the frame's `fork` license, and why is it sound here?
- Where in Graal's IR does the token form's `exc` come from, for a call and for a failed check?

### Part 2: limits

| # | Example | What happens |
| --- | --- | --- |
| 16 | `VolatileField` | refused: a volatile access orders memory with other threads, which tokens don't model |
| 17 | `Synchronized` | refused at `MonitorId`, the lock |
| 18 | `Switch` | refused at `IntegerSwitch`, a branch with more than two successors. A chain of two-way branches would work; it isn't written yet |
| 19 | `OpaqueCall` | translated, but `System.nanoTime()` has no facts: the method's signature is opaque, and it takes every token of the program even with `--partition field` |

For the reasons, see the refusals list in [`src/graal2ct/README.md`](../../src/graal2ct/README.md).

### Part 3: forwarding

Compare `--partition none` with `--partition field`, with `--rules`. The first example explains why all the others put a call between the store and the load: without one, Graal already removes the load before the export.

| # | Example | `none` | `field` | What makes it work, or stops it |
| --- | --- | --- | --- | --- |
| 20 | `ForwardedByGraal` | – | – | the export has no load at all: Graal forwarded the 5 before the analysis |
| 21 | `AcrossCall` | kept | **forwarded** | `length` doesn't take `h_value`, so the load's token comes straight from the store |
| 22 | `WritingCallBlocks` | kept | kept | control: `countInto` writes `Counter.value`, so the call takes `h_value` |
| 23 | `RepeatedLoad` | kept | **forwarded** | a load forwards from an earlier load too |
| 24 | `IntoBranchArm` | kept | **forwarded** | the value is passed down the branch as a new parameter of both arms |
| 25 | `AcrossMerge` | **one arm** | **both arms** | the merge is split: each arm that knows the value jumps to a copy that takes it. With one heap token, only the arm without the call knows it |
| 26 | `IntoLoop` | kept | **forwarded** | the loop header gets the 1 as a parameter, which lasts: nothing in the loop writes the field |
| 27 | `LoopCarried` | kept | **forwarded** | the header's new parameter is a loop-carried phi: the 1 on entry, the stored `i` on the back edge |
| 28 | `OutOfLoop` | kept | **out of the loop** | the first iteration is peeled. One load is left, in the peeled copy, and none in the loop |
| 29 | `WritingCallInLoopBlocks` | kept | kept | control: the call writes the field in every iteration |

**Questions after part 3:**
- In `AcrossCall`, which single instruction stops forwarding under `none`?
- Why can't the load in `OutOfLoop` simply move above the loop?
- `LoopCarried` forwards the load but keeps both stores. Which instruction keeps them? (Part 4 explains it.)

### Part 4: dead stores

| # | Example | `none` | `field` | Why |
| --- | --- | --- | --- | --- |
| 30 | `Adjacent` | **removed** | **removed** | overwritten right away; the export still has both stores |
| 31 | `OtherFieldBetween` | kept | **removed** | per field, the store to `other` takes another token |
| 32 | `BothArms` | **removed** | **removed** | the rule follows the token into both arms: no partitions needed |
| 33 | `OneArmKeeps` | kept | kept | control: one arm returns, and the caller may read the 0 |
| 34 | `CallBetweenKeeps` | kept | kept | the call may throw: its exception branch becomes a guard that `throws`, every token leaves there, and a handler may read the 1 |
| 35 | `ReadThroughAliasKeeps` | kept | kept | control: a load through another reference, which may be the same object, reads the 1 |

`CallBetweenKeeps` is the important one: the call doesn't touch `Counter.value`, yet the store stays. Deleting it would be wrong in Java, because an exception can leave the method between the two stores.

### Part 5: objects

These need the export with allocation sites and `--partition object-field`:

```bash
uv run graal2ct graal-export/out/suite/objects.ForwardPastOtherObject.allocsens.json --method demo --partition object-field --rules
```

To see which partition each access got, run `effects.kills` on the same export:

```bash
uv run python -m effects.kills graal-export/out/suite/objects.ForwardPastOtherObject.allocsens.json -o kills.txt --partition object-field --accesses accesses.txt
```

`accesses.txt` then lists each access, by bytecode position, with its partition.

| # | Example | `field` | `object-field` | Why |
| --- | --- | --- | --- | --- |
| 36 | `ForwardPastOtherObject` | kept | **forwarded** | `main` only passes two different counters, so the store between takes the other object's token |
| 37 | `ForwardPastMaybeAlias` | kept | kept | control: `main` also passes one counter twice, so union-find puts both objects in one set |
| 38 | `CallOnOtherObject` | kept | **forwarded** | `countInto` only ever writes the other counter, so its signature names only that object's partition |
| 39 | `DeadStorePastOtherObject` | kept | **removed** | the load between reads another object's token |
| 40 | `DeadStoreMaybeAlias` | kept | kept | control: again, one counter passed twice |

**Questions after part 5:**
- In `ForwardPastMaybeAlias`, which access joins the two objects?
- What would happen to example 36 if `main` also passed each counter, in turn, to another method that reads `value`? (The union-find is global.)

## Conventions, if you add an example

- **Package:** the part the example belongs to.
- **Class name:** the concept, in a few words. A control says what blocks the rule: `…Blocks`, `…Keeps`, `…MaybeAlias`.
- **One method under study, `demo`,** with a comment that says what to look for.
- **Helpers are recursive,** so that Graal can't inline them before the analysis.
- **Loop bounds come from `args`** (`args.length + 3`), so that Graal can't unroll the loop.
- **Read through a reference first if it must be checked for null before the stores** (`int seen = other.other;`), so that the only thing between the stores is the access under study.
- **`main` prints nothing:** it stores into `sink`, which keeps the export small.
- **Add the example to the expectations in [`check_suite.py`](../../test/export_check/check_suite.py),** and run `make suite`.
