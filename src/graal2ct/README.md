# From Graal IR to graal.ct

[`translate.py`](translate.py) turns each method of an export into a structure of
graal.ct, the dialect of Cthulhu that models Graal IR
([`../cthu/graal.ct`](../cthu/graal.ct)). Each block becomes a λ, a branch an
`opt`/`join` pair with a frame that forks every token, and a loop a λ that jumps
back to itself. Every memory operation takes the token of its partition and
gives the next one. An exception is control flow, as in Graal IR: a method
gives back the exception it threw, and its caller branches on it.

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
| an `Invoke` with several | a call of `dispatch_…`, an external, with the tokens any of the targets takes: the union of their signatures, not all of memory |
| an unresolved `Invoke` | a call with every token |
| an intrinsic that touches memory, class initialization | a call of `graal_<node>`, an external, with every token of the method |
| a call's exception edge, or another node's (`EnsureClassInitialized`, `ArrayCopy`, `CopyOf`) | the call gives back the exception, null if it threw none; the block ends with a branch on it to the normal successor and to where the exception goes |
| `ExceptionObject`, where an exception edge goes | a parameter of that λ: the exception |
| `BytecodeException`, a check that failed | `ref exception`: a new exception, which nothing else has seen |
| `Return` | the result, a null exception and every token |
| `Unwind` | no result (`bot`), the exception and every token |
| `Deoptimize` | a λ that traps on every token: ahead-of-time code never comes back from a deoptimization |

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

## Exceptions

Every call in an export is an `InvokeWithException`: it ends its block, with an
edge for when it returns and one for when it throws. So the translation needs no
block of its own for an exception, only a branch. `forwardAcrossWritingCall`,
per field, without the copies of values:

```
    b2 = λ p0 p1 p2 h_value h_next h_count → r exc h_valueout h_nextout h_countout
        heap set_0 h_value p0 v11 → h_value1                        ; counter.value = 5
        f_rrhh_rhh call k13 p1 p2 h_next h_count → v17 h_next1 h_count1   ; countInto(logger, list)
        ref nil? v17 → v17_none
        …                                                           ; branch: b3 if v17 is null, b4 if not
        f_rrhhh_irhhh call k v17 p0 h_value1 h_next1 h_count1 → r exc h_valueout h_nextout h_countout
    b3 = λ v17 p0 h_value h_next h_count → …                        ; countInto returned
        heap get_0 h_value p0 → v24 h_value1                        ; return counter.value
        ref null → exc
        int move v24 → r
        …
    b4 = λ v17 p0 h_value h_next h_count → …   ; throws: every path from here leaves the method with an exception
        Examples_forwardAcrossWritingCall b5 → k5
        f_rhhh_irhhh call k5 v17 h_value h_next h_count → r exc …
    b1 = λ p0 p1 p2 h_value h_next h_count → …                      ; counter was null; throws
        ref exception → v31                                         ; NullPointerException
        Examples_forwardAcrossWritingCall b5 → k5
        f_rhhh_irhhh call k5 v31 h_value h_next h_count → r exc …
    b5 = λ v30 h_value h_next h_count → r exc …                      ; throws
        ref move v30 → exc                                          ; Unwind: the caller gets it
        int bot → r
        heap move h_value → h_valueout
        …
```

- **`countInto` gives back its exception, `v17`.** The branch on whether it is
  null goes on to `b3`, or to `b4`, the block the exception edge leads to, which
  takes `v17` for its `ExceptionObject`. Both arms of a branch take the same
  parameters, so `b3` takes `v17` too, and drops it.
- **The null check's arm, `b1`, makes the `NullPointerException`.** It and `b4`
  go on to `b5`, the `Unwind`, whose phi is the exception. `b5` gives the caller
  the exception and every token, as a return gives the result.
- **A λ from which every path throws says so.** The rules make a guard of a
  branch to one ([`../rules/README.md`](../rules/README.md)).

A handler is code like any other: an exception edge to a block that doesn't
rethrow is a λ that takes the exception and goes on. Two things stay outside the
token form. A `BytecodeException` makes its exception with no effect, as the
facts say, though it allocates: the object is new, so nothing before can have
seen it. And an allocation's `OutOfMemoryError` has no edge in Graal IR, so the
rules treat an allocation as a place where any path may leave the method.

## What it refuses

- a block that ends in a `switch` (`IntegerSwitch`): only two-way branches are modelled;
- a value the export gives no type;
- a volatile field access, as the export marks it.

On Are We Fast Yet's native image, that leaves 4 of 459 methods; on the
native-image driver, 22 of 449. See [`../../programs/README.md`](../../programs/README.md).
