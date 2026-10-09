# Rules on the token form

[`memory.py`](memory.py) rewrites a translated program in place. It forwards
loads and removes dead stores, and it reads the order of memory operations
off the tokens alone. [`compare.py`](compare.py) puts what the rules leave
next to what Graal leaves.

```bash
uv run graal2ct graal-export/out/examples.json --partition field --rules
```

prints the rewritten program and lists, on stderr, every load forwarded and
every store removed. `make compare` prints the comparison with Graal, and
`uv run pytest test/export_check/check_rules.py` runs the checks.

The listings below show λs the way the rules see them: without `dup` and
`drop`, so each value has one name. The printed program has them back. A
suffix such as `_b3` on a name says that the instruction came from block `b3`
when that block joined the λ. Every example is a method of
`graal-export/examples/Examples.java`.

## In what order

1. A branch to a trap becomes a guard.
2. A block that only one jump reaches joins the λ that jumps.
3. Loads are forwarded: within a λ, into branch arms and across merges, until
   nothing changes.
4. Dead stores go.
5. What nothing uses any more goes, and every λ is put back into single-use
   form.

Steps 1 and 2 only change the shape of the program. They make more of it
straight-line, so that the rules after them can be local: each follows a
token from one operation to the next.

## 1. A branch to a trap becomes a guard

A branch whose one arm traps on every path becomes a `guard` on each token,
which traps when that arm would have run, and a jump to the other arm. Graal
checks for null before every field access, and each check is such a branch,
so without this, every null check would split straight-line code in two.
`guard ∷ H × B → H` is declared in `graal.ct`. Graal has guards of its own,
`FixedGuardNode`.

`forwardAcrossWritingCall` starts with the null check on `counter`:

```
before:
  run = λ p0 p1 p2 h_value h_next h_count → r h_valueout h_nextout h_countout
      ref nil? p0 → v6
      Examples_forwardAcrossWritingCall b1 → kt          ; b1 traps
      Examples_forwardAcrossWritingCall b2 → kf
      Examples_forwardAcrossWritingCall frame_0 → frame
      bool not v6 → cn
      f_rrrhhh_ihhh opt v6 kt → at
      f_rrrhhh_ihhh opt cn kf → af
      f_rrrhhh_ihhh join at af frame → k
      f_rrrhhh_ihhh call k p0 p1 p2 h_value h_next h_count → r h_valueout h_nextout h_countout

after:
  run = λ p0 p1 p2 h_value h_next h_count → r h_valueout h_nextout h_countout
      ref nil? p0 → v6
      heap guard h_value v6 → h_value_g                    ; traps when counter is null
      heap guard h_next v6 → h_next_g
      heap guard h_count v6 → h_count_g
      …                                                    ; b2's code follows
```

## 2. A block that only one jump reaches joins it

Graal ends a block at every call, so a store, a call and a load take two λs
and a jump between them. A λ that only one jump reaches is inlined into the
λ that jumps. A merge, which several λs jump to, stays a λ, and so does a
loop header, which its back edge jumps to again.

In `forwardAcrossWritingCall`, `b2` (the store and the call) joins `run`
after step 1, and `b3` (the load after the call) joins it too. The whole
method is one λ, shown in the next listing.

## 3. Forwarding a load

A load whose value is known becomes a `move` of that value, and its token a
`move` of the token. The value is known when the load's token comes straight
from a store or a load of the same field of the same object. "Straight"
means through moves and guards only: no call, and no other memory operation
on that token, comes in between. With a token per field, a call takes only
the tokens of the fields it may touch, so a call that leaves the field alone
is no obstacle.

### Within a λ

`forwardAcrossWritingCall`, with a token per field:

```java
counter.value = 5;
countInto(logger, list);   // writes Logger.count, reads Link.next
return counter.value;
```

```
  run = λ p0 p1 p2 h_value h_next h_count → r h_valueout h_nextout h_countout
      ref nil? p0 → v6
      heap guard h_value v6 → h_value_g
      heap guard h_next v6 → h_next_g
      heap guard h_count v6 → h_count_g
      int cons_5 → v11_b2
      heap set_3 h_value_g p0 v11_b2 → h_value1_b2         ; counter.value = 5
      Examples_countInto_LExamples_Logger_LExamples_Link__V run → k13_b2
      f_rrhh_hh call k13_b2 p1 p2 h_next_g h_count_g → h_next1_b2 h_count1_b2
      int move v11_b2 → v24_b3   ; forwarded Examples$Counter.value
      heap move h_value1_b2 → h_value1_b3
      int move v24_b3 → r
      heap move h_value1_b3 → h_valueout
      heap move h_next1_b2 → h_nextout
      heap move h_count1_b2 → h_countout
```

The two moves after the call were `heap get_3 h_value1_b2 p0 → v24_b3
h_value1_b3`, the load. The call takes `h_next` and `h_count` only, so the
load's `h_value1_b2` comes straight from the store, through `counter` (`p0`)
both times: the load returns 5. With one heap token, the call takes `h`, the
load's token comes from the call, and nothing is forwarded.

A load forwards from a load the same way. In `repeatedLoadAcrossCall`, the
second load of `counter.value`, after `length(list)`, takes the first one's
value:

```
      heap get_3 h_value_g p0 → v8_b2 h_value1_b2           ; int before = counter.value
      f_rh_ih call k10_b2 p1 h_next_g → v10_b2 h_next1_b2   ; length(list)
      int move v8_b2 → v21_b3   ; forwarded Examples$Counter.value
      heap move h_value1_b2 → h_value1_b3
```

Controls:
- **`forwardAcrossCallControl`:** the callee writes `Counter.value`, so the call takes `h_value`.
- **`forwardMaybeAliasControl`:** the load goes through another reference, which may or may not be the same object.
- **`Signatures`:** after each call that touches everything (a monitor, a volatile store, a native, an unresolved call), the call takes every token.

### Into a branch arm

A load in a branch arm takes the value from above the branches it is in when
its token and its object come down unchanged from there. Each branch on the
way passes the value to both of its arms as a new parameter, because both
arms of a branch share one type, and gets a frame for the new type.

`deadStoreReadInArm`:

```java
counter.value = 1;
int n = length(list);
if (flag) {
    n += counter.value;
}
counter.value = 2;
return n;
```

```
before (after steps 1 and 2):
  run = λ p0 p1 p2 h_value h_next → r h_valueout h_nextout
      …
      int cons_1 → v11_b2
      heap set_3 h_value_g p0 v11_b2 → h_value1_b2             ; counter.value = 1
      f_rh_ih call k13_b2 p1 h_next_g → v13_b2 h_next1_b2      ; length(list)
      …                                                        ; the branch on flag
      f_rihh_ihh call k_b3 p0 v13_b2 h_value1_b2 h_next1_b2 → r h_valueout h_nextout
  b5 = λ p0 v13 h_value h_next → r h_valueout h_nextout        ; the arm where flag holds
      heap get_3 h_value p0 → v29 h_value1
      int add v13 v29 → v33
      …

after:
  run = λ p0 p1 p2 h_value h_next → r h_valueout h_nextout
      …
      f_riihh_ihh call k_b3 p0 v13_b2 v11_b2 h_value1_b2 h_next1_b2 → r h_valueout h_nextout
  b4 = λ p0 v13 v29_in h_value h_next → r h_valueout h_nextout   ; the other arm drops it
      …
  b5 = λ p0 v13 v29_in h_value h_next → r h_valueout h_nextout
      int move v29_in → v29   ; forwarded Examples$Counter.value
      heap move h_value → h_value1
      int add v13 v29 → v33
      …
```

In `b5`, `h_value` is the branch's `h_value1_b2` and `p0` its `p0`: the
token comes straight from the store, through `counter` both times.

The branch now passes `v11_b2`, the 1, and its type has an `int` more:
`f_rihh_ihh` became `f_riihh_ihh`. The call between the store and the branch
takes `h_next` only. With one heap token it takes `h`, and the load stays.

Control:
- **`forwardIntoArmAliasControl`:** the load in the arm goes through another reference. With one heap token, a store to another field also comes between them.

### Across a merge

A merge is a λ that more than one λ jumps to. A load in a merge can take its
value from the predecessors that know it, those whose token comes from a
store or a load of the same field of the same object.

Here is how the merge is split:
- Those predecessors get a copy of the merge, up to the load. In the copy, the load takes the value as a parameter instead, like a phi.
- The other predecessors keep the original merge.
- Both copies go on to a new λ, `…_after`, which holds the code after the load, so nothing after the load is copied.

Only a load with nothing before it but guards and operations that can't throw
is taken, so the copy repeats no call and no memory access. A loop header
isn't split, because that would peel the loop.

#### Every predecessor knows the value: `forwardAcrossMerge`

```java
int n = 0;
if (flag) {
    counter.value = 1;
    n = length(list);
} else {
    counter.value = 2;
}
return counter.value + n;
```

Both arms jump to the merge with the token of their own store. The call in
one arm takes `h_next` only. So both arms jump to the copy, `b8_known`, each
passing the value it stored, and the original merge, which nothing jumps to
any more, goes:

```
  b1 = λ p0 p1 v6 v11 h_value h_next → r h_valueout h_nextout      ; flag false
      …
      heap set_3 h_value_g p0 v37_b3 → h_value1_b3                 ; counter.value = 2
      f_irbihh_ihh call k8_b3 v6 p0 v11 v37_b3 h_value1_b3 h_next_g → r h_valueout h_nextout
  b4 = λ p0 p1 v6 v11 h_value h_next → r h_valueout h_nextout      ; flag true
      …
      heap set_3 h_value_g p0 v16_b6 → h_value1_b6                 ; counter.value = 1
      f_rh_ih call k18_b6 p1 h_next_g → v18_b6 h_next1_b6          ; length(list)
      f_irbihh_ihh call k8_b7 v18_b6 p0 v11 v16_b6 h_value1_b6 h_next1_b6 → r h_valueout h_nextout
  b8_known = λ v40 p0 v11 v48_b10_in h_value h_next → r h_valueout h_nextout
      heap guard h_value v11 → h_value_g
      heap guard h_next v11 → h_next_g
      int move v48_b10_in → v48_b10   ; forwarded Examples$Counter.value
      heap move h_value_g → h_value1_b10
      int add v40 v48_b10 → v51_b10_b8_after
      …
```

With one heap token, the call takes `h`, so only the arm without the call
knows the value, and the merge splits for that arm alone.

#### Only some predecessors know it: `deadStoreReadAfterMerge`

```java
if (flag) {
    counter.value = 1;
}
int seen = counter.value;
counter.value = 2;
return seen;
```

Only the arm that stores knows the value. That arm gets the copy, the other
arm keeps the load, and both go on to `b5_after` with the last store:

```
  b1 = λ p0 v10 h_value → r h_valueout                  ; flag false: still loads
      heap guard h_value v10 → h_value_g_b5
      heap get_3 h_value_g_b5 p0 → v28_b8_b5 h_value1_b8_b5
      f_rih_ih call k_after_b5 p0 v28_b8_b5 h_value1_b8_b5 → r h_valueout
  b2 = λ p0 v10 h_value → r h_valueout                  ; flag true: takes the 1
      heap guard h_value v10 → h_value_g
      int cons_1 → v15_b4
      heap set_3 h_value_g p0 v15_b4 → h_value1_b4        ; counter.value = 1, dead in step 4
      heap guard h_value1_b4 v10 → h_value_g_b5_known
      int move v15_b4 → v28_b8_b5_known   ; forwarded Examples$Counter.value
      heap move h_value_g_b5_known → h_value1_b8_b5_known
      f_rih_ih call k_after_b5_known p0 v28_b8_b5_known h_value1_b8_b5_known → r h_valueout
  b5_after = λ p0 v28_b8 h_value1_b8 → r h_valueout
      int cons_2 → v35_b8
      heap set_3 h_value1_b8 p0 v35_b8 → h_value2_b8      ; counter.value = 2
      int move v28_b8 → r
      heap move h_value2_b8 → h_valueout
```

Graal gets the same result, one store and one load, by duplicating the merge
(`DuplicationPhase`) and eliminating the read on one path.

Control:
- **`forwardAcrossMergeAliasControl`:** the second arm stores through another reference, and with one heap token then to another field, so only the first arm's path takes the value.

## 4. Dead stores

A store goes when every path its token takes overwrites the same field of
the same object before anything can read it. The store becomes a `move` of
its token, and nothing else changes.

The paths follow the token through:
- moves and guards;
- jumps, into a merge as well;
- both arms of a branch.

A loop that neither reads nor overwrites the field adds no path. Any other
use of the token keeps the store:
- a load of the field, through any reference, since another reference may be the same object;
- a store through another reference, which may be another object;
- with one heap token, an access to another field: the rule never looks past a memory operation;
- a call that takes the token;
- leaving the method.

### Per field, not with one heap: `deadStoreOtherField`

```java
counter.value = 1;   // dead
counter.other = 7;
counter.value = 2;
```

```
per field:
      heap move h_value_g → h_value1_b2   ; dead store to Examples$Counter.value
      int cons_7 → v16_b2
      heap set_6 h_other_g p0 v16_b2 → h_other1_b2         ; counter.other = 7
      int cons_2 → v23_b2
      heap set_3 h_value1_b2 p0 v23_b2 → h_value2_b2       ; counter.value = 2

one heap:
      heap set_3 h_g p0 v9_b2 → h1_b2                      ; counter.value = 1: h1_b2 goes to
      heap set_6 h1_b2 p0 v16_b2 → h2_b2                   ; a store to another field, so it stays
      heap set_3 h2_b2 p0 v23_b2 → h3_b2
```

With a token per field, the first store's `h_value1_b2` goes straight to the
second store to `counter.value`. The store to `other` takes `h_other`.
`deadStoreOtherObject` is the same with `logger.count` in between.

### Through both arms, even with one heap: `deadStoreBothArms`

```java
counter.value = 0;   // dead
if (flag) {
    counter.value = 1;
} else {
    counter.value = 2;
}
```

```
  run = λ p0 p1 h → hout
      …
      heap move h_g → h1_b2   ; dead store to Examples$Counter.value
      …                                                    ; the branch on flag
      f_rh_h call k_b2 p0 h1_b2 → hout
  b3 = λ p0 h → hout
      heap set_3 h p0 v34 → h1                             ; counter.value = 2
      …
  b4 = λ p0 h → hout
      heap set_3 h p0 v21 → h1                             ; counter.value = 1
      …
```

The branch passes the token, and `counter` as `p0`, to both arms, and each
arm overwrites the same field of the same object. Nothing else is in between,
so a single heap token is enough.

### After forwarding

A store whose reader was forwarded can be dead too:
- **`deadStoreReadAfterMerge`:** once the load takes the 1 on that path, the store in the arm goes. Its token then goes, through a guard, to the last store.
- **`deadStoreReadInArm`:** once the load in the arm takes the 1, the first store goes.

### Controls

- **`deadStoreMaybeAliasControl`:** a load through another reference may read it.
- **`deadStoreMaybeAliasStoreControl`:** a store through another reference may not overwrite it.
- **`deadStoreOneArm`:** one arm leaves it to the caller.
- **`deadStoreReadInLoop`:** each iteration loads it, and nothing carries a value into a loop.

### The trap model

A path that throws ends in a trap, or at a guard, and that ends the program,
so nothing reads the store on that path. In Java a handler up the stack
could. So a store removed across a call or a guard is legal in Java only if
neither can throw.

Of the five stores removed in `Examples`, four are legal in Java as well:
- In `deadStoreOtherField`, `deadStoreOtherObject` and `deadStoreBothArms`, nothing between the two stores can throw.
- In `deadStoreReadAfterMerge`, the guard in between checks a reference already checked on that path.

The fifth, in `deadStoreReadInArm`, is not: `length(list)` comes between the
stores and may throw `StackOverflowError`. Forwarding a load never depends on
the trap model.

## 5. Clean-up

What nothing uses any more goes:
- values, such as the constant a dead store stored, or the `not` a guard left unused;
- λs nothing takes, such as a trap arm or an old frame.

`linearize` then puts copies and drops back. Every rewritten program passes
the single-use and type checks, and a second pass changes nothing.

## Next to Graal

`make compare` runs `graal-probe` on `Examples` and `Signatures`. Each cell
is the field stores/loads left; "Graal" is the full suite with calls kept as
calls.

| Method | Bytecode | Graal | Graal + inlining | One heap | Per field |
|---|---|---|---|---|---|
| `deadStoreOtherField` | 3/0 | 3/0 | 3/0 | 3/0 | **2/0** |
| `deadStoreBothArms` | 3/0 | 3/0 | 3/0 | **2/0** | **2/0** |
| `deadStoreReadAfterMerge` | 2/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| `deadStoreReadInArm` | 2/1 | 2/1 | 3/1 | 2/1 | **1/0** |
| `forwardAcrossWritingCall` | 1/1 | 1/1 | 1/1 | 1/1 | **1/0** |
| `forwardAcrossMerge` | 2/1 | 2/1 | 2/1 | 2/1 | **2/0** |
| `Signatures.acrossField` | 1/1 | 1/1 | 1/0 | 1/1 | **1/0** |
| **Total, 33 methods** | 49/32 | 48/35 | 59/40 | 47/32 | 44/23 |

How to read it:
- **Inlining column:** inlined callees add accesses to the same fields, so its totals overstate what is left of each method's own accesses.
- **Graal's loads above the bytecode:** loop peeling and merge duplication copy loads.

## What they don't do yet

- **Loops:** nothing carries a value into a loop. A loop header isn't split, and a load in a loop isn't forwarded (`deadStoreReadInLoop`, `hoistLoadOutOfLoop`).
- **A load forwarded into an arm** doesn't tell a merge below it that the value is known.
- **Splitting a merge** only happens for a load with nothing before it but guards and operations that can't throw.
- **Refused methods:** the translation refuses calls with two targets and allocations that went through escape analysis, so the rules never see those methods.

## How the checks keep them honest

`test/export_check/check_rules.py` has one check per rule, each with its
controls. A further check makes sure every rewritten program, under both
partitionings:
- still passes the single-use and type checks;
- parses back;
- is unchanged by a second pass.

Every control was confirmed by breaking a rule on purpose, in 22 different
ways, from ignoring the object to a guard trapping on the wrong arm. Each
break makes a check fail.
