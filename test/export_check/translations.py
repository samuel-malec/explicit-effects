"""What the checks share: the fixtures, their translation, and a look into a translated method."""

from pathlib import Path

from cthu.ir import Program, Structure
from effects.signatures import PARTITIONERS, analyse, no_analysis
from graal.graal_import import load
from graal2ct.translate import Translation

DATA = Path(__file__).resolve().parent.parent / "data"
LOAD_STORE_ELIMINATION = DATA / "loadstoreelimination.json"
SIGNATURES = DATA / "signatures.json"
ALIASING = DATA / "aliasing.json"  # exported with allocation sites


def translate(path: Path, partition: str = "none") -> tuple[Program, Translation]:
    """Every method of the export, under the partitioning."""
    facts, graphs = load(path)
    effects = no_analysis() if partition == "none" else analyse(facts, PARTITIONERS[partition](facts))
    translation = Translation(graphs, effects)
    return translation.translate(sorted(graphs)), translation


def structure(program: Program, name: str) -> Structure:
    return next(s for s in program.structures if s.name == name)


def looping(s: Structure) -> set[str]:
    """The λs on a loop: those that jump or branch, through others of the
    method's λs, back to themselves. A call of the method itself isn't a loop."""
    refs = {lam.name: {i.op for i in lam.body if i.type == s.name and i.op != "run"} for lam in s.lambdas}  # "run": a method's entry
    found = set()
    for start in refs:
        seen, work = set(), list(refs[start])
        while work:
            name = work.pop()
            if name == start:
                found.add(start)
                break
            if name not in seen:
                seen.add(name)
                work.extend(refs.get(name, ()))
    return found
