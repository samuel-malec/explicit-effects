# Archived corpus programs

Programs that left `corpus/` on 3 Nov 2026 because no measurement builds them. The evaluation builds
`LoadStoreElimination`, `Signatures`, `Aliasing` and `Allocation` (loads), and `LockShapes` and `VolatileShapes`
(lock and volatile timings); `LocksShared` stays in `corpus/` for the demonstration of a lock that must stay.
`make`, `graal-native/run.sh` and the checks read only `corpus/`, so nothing here is exported, built or checked.

| Program | What it shows |
| --- | --- |
| `Concurrency` | Calls that synchronize, with real threads: what a kill set may let through them and what it must not. |
| `Locks` | Locks only one thread takes, on objects kept where Graal's escape analysis can't see them go: an array, a field of another object, a call it doesn't inline. |
| `LockCollision` | Two locks in one method that the facts once labelled alike, because a label made of the innermost bytecode index alone was the same for both. |
| `VolatileShared` | A volatile flag another thread raises. The control claims its read is local, and the program must then hang. |

To use one again, move it back:

```bash
git mv graal-export/archive/Locks.java graal-export/corpus/
```
