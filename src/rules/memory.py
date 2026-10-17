"""Memory rules on the token form

The rules run on every method, in this order:
    1. Shape: make the code as straight-line as possible (shape.py).
    2. Load forwarding: a load whose value is already known takes that value
       instead of reading memory (forward.py, loops.py).
    3. Dead stores: a store that is always overwritten before anyone can read
       it goes (stores.py).
    4. Clean-up: what nothing uses any more goes, and the code is put back into
       single-use form.
"""

import warnings
from dataclasses import dataclass, field

from cthu.ir import Program
from cthu.ssu import linearize

from .forward import forward_into_arms, forward_within, split_merge
from .loops import forward_into_loops, hoist_out_of_loop
from .shape import drop_unused, fuse, guard_exits, merge_same_params, remove_unreferenced, unshare
from .stores import remove_dead_stores

ROUNDS = 100  # at most this many merge splits and loop peels per method


@dataclass
class Rewrites:
    """What the rules did, for printing: each forwarded load and each removed
    store. `dead` also says where each removed store was in the bytecode, so
    that Native Image can remove the same store."""
    forwarded: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    dead: list[str] = field(default_factory=list)


def apply(program: Program, forward: bool = True, stores: bool = True) -> Rewrites:
    """Run the rules on every method of the program, and say what changed.

    `forward=False` skips load forwarding. The dead stores sent to Native Image
    use it, because they must be dead on their own, not only because a load
    was forwarded. `forward=False, stores=False` only straightens the code,
    which is what `graal2ct --shape` shows."""
    done = Rewrites()
    for s in program.structures:
        for lam in s.lambdas:
            unshare(lam)
        guard_exits(s)
        
        for _ in range(ROUNDS):
            remove_unreferenced(s)
            fuse(s)
            merge_same_params(s)
            
            if not forward:
                break
            
            for lam in s.lambdas:
                done.forwarded += [f"{s.name}: {note}" for note in forward_within(lam)]
            
            done.forwarded += [f"{s.name}: {note}" for note in forward_into_arms(s)]
            done.forwarded += [f"{s.name}: {note}" for note in forward_into_loops(s)]
            changed = hoist_out_of_loop(s) or split_merge(s)
            
            if changed is None:
                break
            
            done.forwarded.append(f"{s.name}: {changed}")
        else:
            warnings.warn(f"{s.name}: stopped after {ROUNDS} rounds of forwarding, with more left", stacklevel=2)
        
        dead = remove_dead_stores(s) if stores else []
        done.removed += [f"{s.name}: {i.field}" for i in dead]
        done.dead += [f"{i.at}\t{i.field}" for i in dead if i.at]
        remove_unreferenced(s)
        
        for lam in s.lambdas:
            drop_unused(lam)
            linearize(lam)
    
    return done
