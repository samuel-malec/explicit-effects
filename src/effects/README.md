# Heap partitions

[`signatures.py`](signatures.py) splits memory into partitions and gives each
method a signature: the partitions it, or anything it calls, may read or
write. The translation gives each partition its own token, so two operations
are ordered only when they touch the same partition.

That is sound only if the partitions are **disjoint**. Every memory location
must be in exactly one partition, so that two accesses that may touch the
same location always thread the same token. There are four partitionings:

| `--partition` | One partition per | Why it is disjoint |
|---|---|---|
| `none` (one heap) | program | there is only one |
| `field` | field and array element kind | two fields are different memory whatever the objects (Java's type system) |
| `object` | set of objects, with all their fields | union-find: two objects share a set when one access may touch both |
| `object-field` | field of a set of objects | the same, for each field on its own: the product of `field` and `object` |

`object` is the partitioning the paper describes. `object-field` is the
finest of the four.

```bash
uv run graal2ct graal-export/out/aliasing.allocsens.json --partition object-field --rules
uv run pytest test/export_check
make compare
```

## Where the objects come from

The exporter, [`GraphExport.PointsTo`](../../graal-export/GraphExport.java),
lists for every field and array access the objects its receiver may point to.
It writes them in two places:
- as `receivers` on the access's node in the graph;
- in the `accesses` of the method's facts, for the program's own methods.

It finds them by walking from the access's reference back to values that have
a flow in the points-to analysis:
- a parameter, an object load, an invoke's result, an allocation and a constant each have one;
- a phi has its inputs' objects;
- a pi or a proxy has its input's objects.

The receivers are null, meaning unknown, when a flow saturated or a value has
no flow. A static field's receiver is one pseudo-object per class, such as
`Aliasing.<statics>`.

**What the analysis names an object depends on how it runs:**

| Analysis | `counter` in `Examples` | `alias` in `forwardAcrossIterationsAliasControl` |
|---|---|---|
| default (`insens`) | `Examples$Counter` | `Examples$Counter` |
| `-H:AnalysisContextSensitivity=allocsens` | `Examples$Counter@Examples.main([Ljava/lang/String;)V:0` | `…main(…):170`, plus `…:0` from the aliasing call |

By default the analysis names objects by type. Then `object-field` partitions
are exactly the `field` partitions on every example, and `object` partitions
are one per class. Telling two counters apart takes allocation sites. The
Makefile writes `<name>.allocsens.json` next to `<name>.json` whenever an
object partitioning or `make compare` needs it.

## Findings

### 1. Allocation sites switch off primitive tracking and predicates

Every context sensitivity except `insens` also sets `TrackPrimitiveValues`
and `UsePredicates` to false (`PointstoOptions`, with the note
"GR-58495: WP-SCCP is not yet compatible with context-sensitive analysis").
The analysis then stops pruning code behind constant conditions and calls it
decides never return.

| `Examples`, same program | `insens` | `allocsens` |
|---|---|---|
| reachable methods | 66 | 16,760 |
| methods with an unresolved call | 1 | 803 |
| methods with an effect the facts can't name | 1 | 1,178 |
| signatures that touch everything | 2 | 11,672 |
| export time | 1.7 s | 35 s |
| export size | 0.3 MB | 11.6 MB |

The extra methods all come through `System.out.println`. Of the 17,105
methods `Examples.main` reaches through calls, 42 remain without `println`.
`Aliasing`, whose `main` prints nothing, reaches 38 methods with either
analysis, in 1.5 s.

**The program's own code doesn't change.** The 41 graphs of `Examples` are
identical under both analyses apart from the receivers, and so are its
methods' facts and signatures:
`main` is the only one that touches everything, under both. So the cost is in
everything around the program. On a real program, which prints, the larger
reachable set means more opaque callees.

Two consequences for the code:
- **Receivers come from the reference's flow, not from the access's.** Without
  primitive tracking, an `int` field access has no flow of its own.
- **`Examples` and `Signatures` can't be the fixture for object
  partitions.** Their allocation-site exports are over 11 MB each. The fixture is
  a separate program instead,
  [`Aliasing.java`](../../graal-export/examples/Aliasing.java), whose
  allocation-site export is 122 KB (`test/data/aliasing.json`).

### 2. A method is analysed once for all its callers

The analysis is context-insensitive for methods (`allocsens` adds allocation
sites, not calling contexts). A parameter points to every object any caller
passes. Two effects follow:
- **A method called once with one object twice keeps its references
  aliased,** whatever its other callers pass. That is how the alias controls
  of `Examples` stay controls: each now has a second call in `main` that passes
  `counter` twice.
- **A method that should tell objects apart needs callers that never mix
  them.** `Aliasing` has two copies of the writing callee, `countInto` and
  `countIntoAlias`, because one shared callee would mix the showcase's objects
  with the control's.

The union-find is global, too: an access whose receivers include two objects
joins them for the whole program. In `Examples`, every alias control's `alias`
includes `counter`, which every method shares. So all of them join one set,
and on `Examples` the `object-field` partitions leave exactly what the `field`
partitions leave.

## How the partitions are made

`_by_objects` joins, with union-find:
- the objects of each access: `(field, object)` pairs for `object-field`, objects for `object`;
- for an access whose receivers are unknown, every object the listed accesses
  of its field may touch, since it may touch any of them;
- nothing else for an access whose receiver is always null: it touches nothing,
  so its pseudo-object stays alone.

A method outside the program lists no receivers. Its accesses are unknown, but
they are to the platform's fields, which are the rest of memory anyway, and to
arrays: every array of a kind that platform code touches is one set.

Two accesses that may touch the same location share an element, and so a set:
that is the disjointness argument. A field with one set keeps its name,
`Aliasing$Link.next`. Otherwise its sets are named by where their first object
was allocated: `Aliasing$Counter.value@main:199`, or `Aliasing$Counter@main:199`
for `object`.

## Worked example: `forwardAcrossCallOnOtherObject`

```java
static int forwardAcrossCallOnOtherObject(Counter counter, Counter other, Link list) {
    counter.value = 5;
    countInto(other, list);   // writes Counter.value, but only of other
    return counter.value;
}
```

**Per field,** `countInto` writes `Counter.value`, so the call takes
`h_value` and the load after it stays. Graal keeps it too: in its model the
call may write anything.

**With allocation sites,** `main` allocates `counter` at bci 199 and `other` at
bci 206. `countInto` is only ever passed `other`, so it writes only
`Counter.value@main:206`. The call takes that token and `h_next`. Counter's
token goes from the store straight to the next λ, where the load takes the 5.
Before the rules, without `dup`:

```
b2 = λ p0 p1 p2 h_value_main_199_ h_value_main_206_ h_next → …
    int cons_5 → v11
    heap set_0 h_value_main_199_ p0 v11 → h_value_main_199_1        ; counter.value = 5
    Aliasing_countInto run → k13
    f_rrhh_hh call k13 p1 p2 h_value_main_206_ h_next → h_value_main_206_1 h_next1   ; countInto(other, list)
    f_rhhh_ihhh call k3 p0 h_value_main_199_1 h_value_main_206_1 h_next1 → …
```

A token name that ends in a digit gets a `_`, so that a version number can
follow it: `h_value_main_199_1` is version 1 of `h_value_main_199_`.

## Results

`make compare` on the allocation-site exports, as stores/loads left:

| `Aliasing` | Graal | Per field | Object | Object-field |
|---|---|---|---|---|
| `forwardPastOtherObject` | 2/1 | 2/1 | **2/0** | **2/0** |
| `deadStorePastOtherObject` | 2/2 | 2/2 | **1/2** | **1/2** |
| `forwardIntoLoopPastOtherObject` | 3/2 | 2/1 | **2/0** | **2/0** |
| `forwardAcrossCallOnOtherObject` | 1/1 | 1/1 | **1/0** | **1/0** |
| each of the four `…AliasControl`s | as bytecode or more | as bytecode | as bytecode | as bytecode |
| **Total, 11 methods** | 18/17 | 16/15 | 15/12 | 15/12 |

- **Dead store:** the one removed is legal in Java. `deadStorePastOtherObject`
  reads `other.other` first, which checks `other` for null, so nothing between
  the two stores can throw.
- **Loop:** in `forwardIntoLoopPastOtherObject` the loop keeps only the store
  `other.value = i`. Graal keeps the load and the store in the loop.

| `Examples` + `Signatures`, 38 methods | Graal | Per field | Object | Object-field |
|---|---|---|---|---|
| stores/loads left | 64/45 | 51/27 | 52/27 | 51/27 |

`object` loses one store to `field` here. `deadStoreOtherField` stores
`value`, then `other`, then `value` again on one counter. With all of an
object's fields in one partition, the store to `other` stands between the two
stores to `value`, as it does with one heap. That is the case for presenting
`object-field` next to the paper's `object`.

## Kills for Graal

[`kills.py`](kills.py) turns the signatures into what each method may write:
`any`, or the partitions it writes. The round trip in
[`graal-native`](../../graal-native/README.md) narrows each call in a native
image to that.
- **With `--partition field`,** the kills are fields and array kinds, which are
  Graal's own locations.
- **With `--partition object-field`,** they are fields of sets of objects.
  `--accesses` then gives each access its partition by where it is, and the
  image gives each access to a field the location of its partition. That
  takes a location per partition, which the graal tree's
  `FieldLocationIdentity` now has.

## Limits

- **Global sets.** One access that may touch two objects joins them
  everywhere. Partitions per method would be finer, but a call would then
  have to split and join tokens where its callee partitions memory
  differently.
- **No calling contexts.** A helper that two callers pass different objects
  mixes them. The analysis's `_1obj` and `_2obj1h` have calling contexts, but
  the facts and the translation have one version of each method.
- **Heap contexts are left out of the names.** Objects that differ only in
  their heap context get one name, which is sound but coarser.
- **Arrays.** Platform code lists no receivers, so its arrays of one kind are
  one set. The translation still refuses array accesses, so arrays only reach
  signatures.

## Checks

- **`check_object_partitions`** (`check_graal2ct.py`):
  - any two listed accesses whose receivers meet are in one partition;
  - `forwardPastOtherObject` has two `Counter.value` partitions, and its control one;
  - `countInto` writes only `other`'s;
  - an access with unknown receivers joins every object of its field;
  - named by type, `object-field` is `field`.
- **`check_object_partitions_tell_objects_apart`** (`check_rules.py`): per
  field the rules change nothing in `Aliasing`; with either object
  partitioning they make the four rewrites above, and leave the controls.
- **`check_rewritten_programs_stay_valid`** now runs every fixture under all
  four partitionings.

Six mutations of the partitioner are each caught:
- an access joins nothing;
- an unknown access joins nothing;
- receivers are ignored;
- per field forgets the field;
- the listed accesses are ignored;
- a method's accesses don't reach its signature.

The 32 mutations of the rules are still caught.
