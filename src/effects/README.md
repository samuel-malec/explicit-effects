# Heap partitions

[`signatures.py`](signatures.py) splits memory into partitions.
Then it annotates functions signatures based on the partitions it, or anything it calls, may read or
write. The translation gives each partition its own token.

That is sound only if the partitions are **disjoint**. Every memory location
must be in exactly one partition, so that two accesses that may touch the
same location always thread the same token. There are four types of partitionings:

| `--partition` | One partition per 
|---|---
| `none` (one heap) | program
| `field` | field and array element kind 
| `object` | set of objects, with all their fields 
| `object-field` | field of a set of objects


```bash
uv run graal2ct graal-export/out/aliasing.allocsens.json --partition object-field --rules
uv run pytest test/export_check
make compare
```


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

A field of an object that no listed access of that field names, as a new
object's can be, is in the partition of the field's accesses with unknown
receivers, if it has any: only those touch it. Until step 9, `object` put it in
its object's partition instead, so a new object's initialization and an unknown
access to the same location could take different tokens. None of the five
programs in the design chapter's table has such an initialization, and no rule
could have used one, but `check_object_partitions` now covers it.

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

| `Examples` + `Signatures`, 39 methods | Graal | Per field | Object | Object-field |
|---|---|---|---|---|
| stores/loads left | 65/46 | 59/27 | 60/27 | 59/27 |

Since step 10 a store is dead only if it is dead in Java, which keeps seven
stores the earlier model removed (52, 53 and 52 stores before;
[`../rules/README.md`](../rules/README.md#4-dead-stores)).

`object` loses one store to `field` here. `deadStoreOtherField` stores
`value`, then `other`, then `value` again on one counter. With all of an
object's fields in one partition, the store to `other` stands between the two
stores to `value`, as it does with one heap. That is the case for presenting
`object-field` next to the paper's `object`.

## Kills for Graal

[`kills.py`](kills.py) turns the facts into what each method, or anything it
calls, may write: `any`, or a list. The round trip in
[`graal-native`](../../graal-native/README.md) narrows each call in a native
image to that. The list holds:
- **the program's partitions.** With `--partition field` they are fields and
  array kinds, which are Graal's own locations. With `--partition object-field`
  they are fields of sets of objects; `--accesses` then gives each access its
  partition by where it is, and the image gives each access to a field the
  location of its partition, which the graal tree's `FieldLocationIdentity` now
  has.
- **the platform's fields, by name,** `java.lang.Throwable.stackTrace`. A kill is
  a location, so a platform field is as good as one of the program's. They used
  to be the rest of memory, which turned any call that reached one into `any`.
- **the VM's own locations Graal names,** `vm:identityHashCode`.
- **`init`** when it allocates: the new objects' initialization.

A method kills `any` when it, or something it calls, has no facts, makes a call
the analysis can't resolve, or has an effect that may write anything. An
effect that may read anything doesn't count: it changes nothing a caller could
read, though the tokens still treat it as touching everything.

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
  - a field of an object no listed access of it names is in that access's partition, under both object partitionings;
  - named by type, `object-field` is `field`.
- **`check_object_partitions_tell_objects_apart`** (`check_rules.py`): per
  field the rules change nothing in `Aliasing`; with either object
  partitioning they make the four rewrites above, and leave the controls.
- **`check_rewritten_programs_stay_valid`** now runs every fixture under all
  four partitionings.

Seven mutations of the partitioner are each caught:
- an access joins nothing;
- an unknown access joins nothing;
- receivers are ignored;
- per field forgets the field;
- the listed accesses are ignored;
- a method's accesses don't reach its signature;
- an object's field that no listed access names keeps its object's partition (step 9).

The 32 mutations of the rules are still caught.
