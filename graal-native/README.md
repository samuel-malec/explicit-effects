# The round trip into Native Image

Our tool works out what each method may write, which objects each field
access may touch, and which stores are dead. This directory gives those
answers back to Graal, in one `native-image` build, and lets Graal's own
phases do the optimizing:

1. Native Image's points-to analysis runs as usual.
2. [`EffectsFeature`](EffectsFeature.java), after the analysis, exports its
   facts with graal-export's exporter: the same facts the standalone analyzer
   gives, but from the image's own analysis.
3. It runs our tool on them,
   [`effects.kills`](../src/effects/kills.py). For each method, that gives
   what it, or anything it calls, may write, or `any` when its signature
   touches everything or it allocates. With objects told apart, it also gives
   each field access its partition of the objects.
4. Before Graal compiles a method of the program, a phase at the start of the
   high tier narrows each call in it, so it kills only what its callees may
   write instead of all of memory. With objects told apart, it also gives each
   field access the location of its partition. With decisions, it first
   removes the stores our rules find dead in Java.
5. Graal's own phases do the rest.
6. A phase at the end of the low tier counts the field stores, field loads and
   calls left in the program's methods, as graal-probe does on the JIT.

```bash
make native                     # every compared program, and the three controls
graal-native/run.sh Examples    # one program: out/examples/{graal,kills,objects,decisions}/
make compare                    # then sets the images next to the JIT and the rules
```

`run.sh` builds each image four times, and checks that each prints what the
JVM prints and exits as it does:

| Image | Analysis | What Graal gets |
|---|---|---|
| `graal` | as usual | nothing: Graal compiles as it does |
| `kills` | as usual | each call kills only the fields its callees may write (step 2) |
| `objects` | allocation sites (`-H:AnalysisContextSensitivity=allocsens`) | each access to a field in its partition of the objects, and calls kill partitions (step 3) |
| `decisions` | allocation sites | the same, with the stores our rules find dead in Java removed (step 4) |

## The change in the Graal tree

Seven files under `compiler/src/jdk.graal.compiler/src/jdk/graal/compiler/`.
All of it is binary compatible, so only `graal.jar` is rebuilt:

```bash
cd ~/graal/compiler && JAVA_HOME=~/.mx/jdks/labsjdk-ce-latest-jvmci-25.4-b23_amd64 mx build --dependencies GRAAL
```

The GraalVM's own builder then runs with
`-J--upgrade-module-path=.../graal.jar`, without rebuilding the GraalVM. On the
JIT nothing changes: graal-probe prints the same for `Examples`, `Signatures`
and `Aliasing` with the new `graal.jar`. Every invoke still kills everything
and every access has its field's location unless narrowed.

### Kill sets on invokes (step 2)

An invoke kills one location, `LocationIdentity.any()`:
- `Invoke` extends `SingleMemoryKill`;
- `InvokeWithExceptionNode` always returns `any()`;
- `InvokeNode` takes one location, fixed when it is made.

Graal can express a node that kills several locations, a `MultiMemoryKill`.
Its read elimination, floating reads, scheduling and loop kill sets all handle
one.

Making every invoke a multi kill would send every compilation through the
code that only knows single kills. That includes `InsertProxyPhase` right
after parsing, and the snippet lowering's check of what a node kills. Instead:
- **`nodes/Invoke`:** `setKilledLocationIdentities(LocationIdentity...)`, and
  the canonical kill set. It is `any()` alone if `any()` is in it, and has no
  duplicates.
- **`nodes/InvokeNode` and `nodes/InvokeWithExceptionNode`:** both keep a kill
  set, `{any()}` until narrowed, and implement both interfaces.
  - As a single kill: `NO_LOCATION` for none, which makes the invoke no memory
    kill at all; the location itself for one; and `any()` for two or more,
    which is sound for code that only knows single kills.
  - Turning an `InvokeWithExceptionNode` into an `InvokeNode` keeps the set.
- **`nodes/memory/MemoryKill.isSingleMemoryKill` / `isMultiMemoryKill`:** a node
  that implements both is a multi kill exactly when it kills two or more
  locations. The phases that handle memory dispatch through these two helpers.

### Field partitions (step 3)

Locations only overlap when they are equal (`LocationIdentity.overlaps` is
final), so the field in one partition of the objects is a location of its own:
- **`nodes/FieldLocationIdentity`:** an optional partition, compared in
  `equals`. The field's locations without one keep their hash code.
- **`nodes/java/AccessFieldNode`:** `setLocationIdentity`, since the location
  was fixed when the node was made.
- **`replacements/DefaultJavaLoweringProvider`:** lowering a field access keeps
  the partition. Native Image's `overrideFieldLocationIdentity` makes a new
  location from the field alone.

## How the accesses get their partitions

- **Where each access is.** The exporter writes each access's position, a
  method and bci with the calls it was inlined through, next to its receivers.
  Native Image drops positions after its analysis, "to reduce memory
  pressure", unless Graal's `TrackNodeSourcePosition` is on. The `objects`
  image is built with `-H:+TrackNodeSourcePosition`.
- **All of a field, or none of it.** A graph's accesses to a field all get
  their partitions, or all keep the field's location. That holds when every
  one of them has a partition and they aren't all in one. Mixed, a plain
  access and a partitioned one would not overlap, and nothing would order
  them.
  - Immutable fields keep theirs: Native Image counts a field it never sees
    written as immutable, which overlaps nothing anyway.
  - `CheckPartitions`, at the start of the mid tier, stops the build if a later
    phase made a mixed graph anyway, say by making a new access.
- **A call kills the partitions its callees write, and their fields too.**
  Graal's read elimination in the high tier keys field accesses by the field
  alone: `new FieldLocationIdentity(load.field())`, whatever the node's
  location. So for a field the graph partitions, a call kills the field
  as a whole, for read elimination, and the partition, for everything that
  goes by the node's location. Floating reads in the mid tier are where
  partitions pay off.

Worked example, `forwardAcrossCallOnOtherObject`:
1. `main` allocates `counter` at bci 199 and `other` at bci 206. `countInto`
   only ever gets `other`.
2. The tool says `countInto` writes `Counter.value@main:206`, and that this
   method's store and load of `counter.value` are in `Counter.value@main:199`.
3. The call kills `value value@main:206`: the plain field for read elimination,
   and other's partition.
4. Read elimination, by the field alone, keeps the load. After lowering, the
   load's location is `value@main:199`, which nothing between the store and
   the load kills.
5. Its floating read takes the store as its memory input and the 5 as its
   value: 1/1 becomes 1/0.

## Dead stores back to Graal

Facts let Graal's own phases do the forwarding. Removing dead stores needs our
decisions: the one rule we saw Graal remove a dead store with wants the two
stores adjacent (finding 1). [`rules.decisions`](../src/rules/decisions.py) gives those
decisions, and the feature removes each such store before Graal compiles.
Three conditions decide which stores go:
- **Legal in Java.** The rules' dead stores rely on the trap model: a path
  that throws reads nothing. In a compiled Java program an exception can leave
  the method, and a handler up the stack can read the store. So the decisions
  run the rules in Java (`memory.apply(java=True)`). A store goes only if
  nothing between it and its overwrite may throw, on any token: a call, a
  guard, a trap, an allocation, a division.
- **Without forwarding.** A store can be dead only because the rules took away
  the load that read it, as in `deadStoreReadAfterMerge`. Graal keeps that
  load unless it forwards it itself, and it would then read stale memory. So
  the decisions shape the program and remove dead stores without forwarding a
  single load first. A store the rules copied counts only if every copy goes.
- **By where it is.** Each store carries its position into the token form, a
  method and bci from the exported graph's node, and the feature removes the
  `StoreFieldNode` there.

`Examples` gets three, all of them legal in Java: the first store of
`deadStoreOtherField`, `deadStoreOtherObject` and `deadStoreBothArms`.
`Aliasing` gets `deadStorePastOtherObject`'s, which Graal also removes on
its own once objects are told apart.

## Findings

`make compare` on the 49 methods of `Examples`, `Signatures` and `Aliasing`,
as stores/loads left:

| | JIT, no inlining | Native Image | with our kills | with objects told apart | with our dead stores too | Our rules, per field | Our rules, objects |
|---|---|---|---|---|---|---|---|
| **All 49 methods** | 82/62 | 82/59 | **82/43** | **81/42** | **78/42** | 67/42 | 66/39 |
| **Inside loops, 9 methods** | 5/9 | 5/9 | **5/5** | **5/4** | **5/4** | 3/5 | 3/4 |

What each kind of answer gives Graal, as the plan's three-way measurement:

| From | Loads | Stores |
|---|---|---|
| Graal alone | 59 | 82 |
| the facts: kills and object partitions (steps 2 and 3) | −17 | −1 |
| the token form's decisions: dead stores in Java (step 4) | 0 | −3 |
| left | 42 | 78 |

### 1. Narrowed, Graal forwards loads itself

With the narrowed calls, Graal removes 16 more loads, almost as many as our
rules:

| Method | Native Image | with our kills | Our rules |
|---|---|---|---|
| `forwardAcrossCall` | 1/1 | **1/0** | 1/0 |
| `forwardAcrossWritingCall` | 1/1 | **1/0** | 1/0 |
| `forwardAcrossMerge` | 2/1 | **2/0** | 2/0 |
| `repeatedLoadAcrossCall` | 0/2 | **0/1** | 0/1 |
| `deadStoreReadInArm` | 2/1 | **2/0** | 1/0 |
| `deadStoreReadInLoop` | 2/1 | **2/0** | 1/0 |
| `forwardAcrossIterations` | 4/2 | **4/0** | 1/0 |
| `forwardAcrossIterationsPeeled` | 4/2 | **4/1** | 1/1 |
| `hoistLoadOutOfLoop` | 0/2 | **0/1**, none in the loop | 0/1 |
| `forwardAcrossVirtualCall` | 1/1 | **1/0** | refused |
| `Signatures.acrossArray` | 1/1 | **1/0** | 1/0 |
| `Signatures.acrossField` | 1/1 | **1/0** | 1/0 |

- **The controls keep their loads.** `forwardAcrossCallControl`,
  `hoistLoadOutOfLoopControl` and `repeatedLoadAcrossCallControl` call
  `countInto` for a counter, which writes `Counter.value`.
  - In `forwardAcrossIterationsAliasControl` and
    `forwardAcrossMergeAliasControl`, one load goes. It is a copy that Graal's
    own peeling or merge duplication made: the load of the peeled first
    iteration, which reads the 1 stored before the loop, or the load on the
    path whose arm stored the value.
  - The loop's load and the other path's load stay, as with our rules.
- **`forwardAcrossVirtualCall`, which our translation refuses**, is forwarded.
  Both `Shape.area()` implementations write nothing, so the call kills nothing.
- **Dead stores stay.** The image keeps 82 stores, counting the copies its
  peeling makes; our rules leave 67 of the export's 76.
  - The dead store Graal does remove in finding 2 goes through a rule in
    `WriteNode.simplify`. It removes a write if the next node in control flow
    writes the same address and has the first as its only memory user.
  - No example has two stores like that, with or without kills. Removing the
    others needs our decisions sent back, not facts: finding 3.

The narrowing touched calls in the program's methods only, their `main`s
included:

| Program | to nothing | to one location | to several |
|---|---|---|---|
| `Examples` | 21 | 23 | 15 |
| `Signatures` | 0 | 2 | 3 |
| `Aliasing` | 3 | 16 | 0 |

A call to `length` kills nothing. A call to `countInto` for a Logger kills
`Logger.count`. The calls in `main` kill several locations each, so the
multi-kill path ran in real compilations.

### 2. With objects told apart, Graal also forwards past other objects

| `Aliasing` | with our kills | with objects told apart | Our rules, objects |
|---|---|---|---|
| `forwardPastOtherObject` | 2/1 | **2/0** | 2/0 |
| `forwardAcrossCallOnOtherObject` | 1/1 | **1/0** | 1/0 |
| `forwardIntoLoopPastOtherObject` | 3/1, a load in the loop | **3/0** | 2/0 |
| `deadStorePastOtherObject` | 2/1 | **1/2** | 1/2 |
| each `…AliasControl` | as without objects | as without objects, or one load more | as without objects |

- **Three loads go**, past another object's store, across a call that writes
  only other objects, and in a loop that stores to another object.
- **A dead store goes too.** In `deadStorePastOtherObject`, `other.value` is
  read between the two stores to `counter.value`.
  - Without partitions, that load reads the first store's memory, so the first
    store has two users.
  - With them, the load floats off in its own partition. The two stores become
    adjacent, and `WriteNode.simplify` removes the first. Our rules remove the
    same store.
- **`Examples` gains nothing.** Its alias controls also get one counter twice,
  so its counters all join one partition per field.
- **Allocation sites cost Native Image's primitive tracking.** The `objects`
  image reads `Counter.other` in `deadStorePastOtherObject` and its control,
  where the others don't. That field is never written, and the default
  analysis folds it to 0. With allocation sites, it tracks no primitive values
  (finding 1 of [`src/effects/README.md`](../src/effects/README.md)). That
  makes up the two loads by which the image's loads drop only from 43 to 42.

### 3. Our decisions remove the dead stores that are legal in Java

| Method | with objects told apart | with our dead stores too | Our rules |
|---|---|---|---|
| `deadStoreOtherField` | 3/0 | **2/0** | 2/0 |
| `deadStoreOtherObject` | 3/1 | **2/1** | 2/1 |
| `deadStoreBothArms` | 3/0 | **2/0** | 2/0 |

- **The six others our rules remove need the trap model,** so they stay in the
  image:
  - `deadStoreReadInArm` and `deadStoreReadInLoop`, one each;
  - `forwardAcrossIterations` and `forwardAcrossIterationsPeeled`, two each.

  In each, `length(list)` comes between the two stores and may throw
  `StackOverflowError`. Sending them would need exceptions modelled: an
  exceptional exit that reads every token.
- **Java mode misses one store that is legal.** In `deadStoreReadAfterMerge`,
  a null check stands between the two stores. It repeats a check already made
  on that path, but the rules don't know that. Graal removes one of the two
  stores on its own anyway: 1/1 in every image.
- **What is left between the image and our rules** (78/42 against 66/39):
  - **12 stores:** six are the stores above, which need the trap model. The
    other six are copies Graal's loop peeling makes, one in each of six loop
    methods.
  - **3 loads:**
    - two are peeled copies, in `hoistLoadOutOfLoopControl` and
      `hoistLoadOutOfLoopListControl`;
    - two are behind calls to allocating callees, which still kill
      everything, in `Signatures.acrossAllocation` and `acrossFinalField`;
    - one goes the other way: the closed world removes it in
      `acrossUnresolved` (finding 6).

### 4. What stays as before

- **Allocation.** A callee that allocates writes the rest of memory, so its
  calls kill everything. This is why `Signatures.acrossAllocation` and
  `acrossFinalField` keep their loads in the image while our rules forward
  them. The rules see allocation touch only the rest of memory, which a
  `Counter.value` load isn't in. Mapping allocation to Graal's
  `INIT_LOCATION` would narrow those too.
- **Calls outside the program's methods** keep killing everything. The facts
  cover the JDK too, and Native Image's run-time class initialization, a kill
  of `any()`, makes a method touch everything. But narrowing only the
  program's calls keeps a mistake in the facts out of the JDK's code.
- **Arrays** keep a location per element kind. The tool partitions them too,
  but the image's kills map a partition of an array kind back to the kind.
which fields it reads and which it writes

### 5. Correctness

Every image prints what the JVM prints and exits as it does: `Examples`'
177, `Aliasing`'s 48, and `Signatures`' exception, in all four modes. Each
control makes one wrong claim, and its image must print something else:

- **`LIE`** claims that `countInto` for a counter writes nothing. Its image
  prints 167 instead of 177, because the methods that call it, such as
  `forwardAcrossCallControl`, then forward a value it changed.
- **`SPLIT`** claims that different references in `forwardPastAliasControl`
  never meet, as an unsound points-to analysis would. Its image prints 47
  instead of 48: in the call that passes one counter twice, the load takes
  the 1 that `alias.value = 2` overwrote.
- **`DEAD`** claims that the store of 2 in `forwardAcrossMerge`'s else arm is
  dead, though the load after the merge reads it. Its image prints 183
  instead of 177: the method returns the 5 the previous one stored.

A store a control removes must be read before something overwrites it. The
first `DEAD` claimed the first store of `deadStoreOneArm`, which is read
when its arm doesn't store. That image printed 177, because the next method
`main` calls stores to the same field before anything reads it.

A first version of `SPLIT` gave every access a partition of its own, and its
image printed 48. A wrong partition only cuts an ordering. The load had no
store left to take its value from, so it read memory, and the scheduler put
that read after the stores anyway. A lie shows when it lets Graal forward a
wrong value, so the control now claims what a points-to mistake would:
accesses through one reference meet, and through different ones don't.

### 6. Native Image specializes on the closed world

`Examples.main` used to pass the literal 3 as every loop's trip count. The
image's analysis propagates constants into parameters, so each loop method
was compiled for exactly 3 iterations. Its loop unrolled completely, which
left 3 calls, 3 loads and no loop. `main` now passes `args.length + 3`, as
`Aliasing`'s does. graal-probe never saw this, because the JIT compiles each
method on its own.

`Signatures.acrossUnresolved` shows the same thing. `main` passes it null
for `s`, so the image proves that `s.take(2)` always throws. The load after
the call goes without any kills.

### 7. Cost

- **`kills` images:** exporting the analysis (9,172 reachable methods) and
  running our tool add about 2.5 s to a 14 s build. The export is 4.4 MB, and
  the kills 0.7 MB.
- **`objects` images:** they take 22 to 24 s for `Aliasing` and `Examples`,
  with allocation sites and source positions. **`decisions` images** take
  about as long: translating the program's methods and running the rules
  takes about a second, within the builds' noise.
  - `Signatures` takes 45 s. With allocation sites, the analysis reaches JDK
    code that the default one prunes.
  - Two such methods have graphs that can't be decoded again after the
    analysis: a Native Image plugin refuses to run once the analysis seals its
    registries. The exporter takes them to touch everything.

### Limits

- **Single-kill code.** `InsertProxyPhase` only proxies single kills, and
  snippet lowering asserts that a replaced node isn't a multi kill. Neither
  meets a narrowed invoke here: `InsertProxyPhase` runs right after parsing,
  before the narrowing, and invokes aren't lowered with snippets in Native
  Image. A pipeline that did either would need them taught multi kills.
- **New accesses.** Graal makes new field accesses for trusted final fields,
  unsafe accesses it turns into field accesses, and `clone`. Partitions go on
  mutable fields only. A new access to one of those after the partitioning
  would stop the build in `CheckPartitions`, rather than go unordered.
- **Read elimination in the high tier** stays per field, since it keys accesses
  by their field. Only the phases from the floating reads on see partitions.
- **Inlining.** A callee inlined after the narrowing brings its own calls,
  which kill everything, and its own accesses, whose positions point into it.
  With `-H:-AOTTrivialInline`, as here, each example is compiled on its own.
- **Run-time compilation.** The phases are only registered for the image's
  ahead-of-time compilation, not for run-time compilation.
- **Only dead stores go back as decisions.** Loads the rules forward are left
  to Graal, which forwards them itself given the facts (finding 1). The
  decisions also leave out stores in methods the translation refuses.
