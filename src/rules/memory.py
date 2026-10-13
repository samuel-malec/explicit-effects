""" Memory rules on the token form.

    - Shape: a branch to an arm that throws becomes guards, and a λ that only
      one jump reaches joins the λ that jumps, so that code is straight-line.
    - Load forwarding: within a λ, into branch arms, into loops, across merges,
      and out of a loop by peeling its first iteration.
    - Dead store removal: a store that every path overwrites before anything
      may read it, an exception leaving the method included.
"""

import warnings
from dataclasses import dataclass, field

from cthu.ir import Program
from cthu.ssu import linearize

from .forward import forward_into_arms, forward_within, split_merge
from .loops import forward_into_loops, hoist_out_of_loop
from .shape import drop_unused, fuse, guard_exits, merge_same_params, remove_unreferenced, unshare
from .stores import remove_dead_stores

ROUNDS = 100  # merges split and loops peeled per method, at most


@dataclass
class Rewrites:
    """What the rules did: `structure: field` for each load and store, and
    where each removed store is: its position, a tab, and its field."""
    forwarded: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    dead: list[str] = field(default_factory=list)


def apply(program: Program, forward: bool = True) -> Rewrites:
    """Rewrite the program in place, and say what changed. Without `forward`,
    only the shape changes before dead stores go: a store is then dead
    whatever happens to the loads."""
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
        
        dead = remove_dead_stores(s)
        done.removed += [f"{s.name}: {i.field}" for i in dead]
        done.dead += [f"{i.at}\t{i.field}" for i in dead if i.at]
        remove_unreferenced(s)
        
        for lam in s.lambdas:
            drop_unused(lam)
            linearize(lam)
    
    return done
