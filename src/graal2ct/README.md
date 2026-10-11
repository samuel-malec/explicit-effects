# From Graal IR to graal.ct

[`translate.py`](translate.py) turns each method of an export into a structure of
graal.ct, the dialect of Cthulhu that models Graal IR
([`../cthu/graal.ct`](../cthu/graal.ct)). Each block becomes a λ, a branch an
`opt`/`join` pair with a frame that forks every token, a loop a λ that jumps back
to itself, and a path that throws a `trap`. Every memory operation takes the
token of its partition and gives the next one.

```bash
uv run graal2ct graal-export/out/examples.json --method forwardAcrossWritingCall --partition field
```

## What each node becomes

| Graal IR | graal.ct |
|---|---|
| a constant int or long, null | `int cons_5`, `long cons_m1`, `ref null` |
| any other constant: an object, a string, a float | `T const_k`, the program's k-th `constant` |
| arithmetic, comparisons, `Abs`, `Sqrt`, `Min`, `Max` | `int add`, `double lt?`, `long abs`, … |
| `Narrow`, `SignExtend`, `ZeroExtend`, `FloatConvert`, `Reinterpret` | `int to_long`, `double to_int`, … |
| `IntegerNormalizeCompare`, `FloatNormalizeCompare` | `long cmp` |
| `IntegerTest`, `ShortCircuitOr` | `and` and `eq?`; `bool or`, `bool not` |
| `InstanceOf`, `InstanceOfDynamic` | `ref instanceof_k`; `ref isinstance` |
| `LoadHub`, `GetClass`, `LoadArrayComponentHub`, `Unbox` | `ref hub`, `ref unbox_int`: what never changes |
| `LoadField`, `StoreField` | `heap get_k`, `heap set_k` (`getstatic`, `setstatic`) |
| `LoadIndexed`, `StoreIndexed` | `heap aget_int`, `heap aset_Object`: the array kind's token |
| `NewInstance`, `NewArray` | `heap new_k`, `heap newarray_int`: the rest of memory's token |
| `CommitAllocation`, with its `VirtualInstance`s and `VirtualArray`s | `new_k` or `newarray_K` for each, then `init_k` or `aset_K` for each field or element |
| `AllocatedObject` | the object its commit made |
| an `Invoke` with one target | a call of that method's structure, with the tokens of its signature |
| an `Invoke` with several | a call of `dispatch_…`, an external, with the tokens of every target |
| an unresolved `Invoke` | a call with every token |
| an intrinsic that touches memory, class initialization | a call of `graal_<node>`, an external, with every token of the method |

`init_k` is a store to an object escape analysis left virtual, as it is made.
The rules treat it as a store, so a later load can take its value; the counts
leave it out, as Native Image does, which writes it as initialization.

When a new object's field is in no partition of the method's signature, its
`init_k` is left out. Nothing in the method or its callees touches that
partition, and the object is new, so no ordering depends on it. The facts leave
such initializations out too.

An intrinsic or class initialization takes every token of the method. That is
sound because the method's signature comes from the same nodes: the facts give
each of them the locations Graal says it touches, or all of memory.

## What it refuses

- a block that ends in a `switch` (`IntegerSwitch`): only two-way branches are modelled;
- a method whose exception handler can be reached: paths that throw are traps;
- a value the export gives no type;
- a volatile field access, as the export marks it.

On Are We Fast Yet's native image, that leaves 4 of 459 methods; on the
native-image driver, 22 of 449. See [`../../programs/README.md`](../../programs/README.md).
