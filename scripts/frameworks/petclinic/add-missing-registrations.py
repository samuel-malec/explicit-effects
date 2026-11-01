"""Add to a reachability-metadata.json the registrations a petclinic image says it misses (its MissingReflectionRegistrationError
messages print the exact entry), after building and running it. Usage: petclinic-fix.py <server.log> <reachability-metadata.json>.
Prints the number of entries added (0: the log holds no such message)."""
import json, re, sys
from pathlib import Path

log = Path(sys.argv[1]).read_text(errors="replace")
target = Path(sys.argv[2])
data = json.loads(target.read_text()) if target.exists() else {"reflection": []}
by_type = {e["type"]: e for e in data["reflection"]}
added = 0
for m in re.finditer(r"add the following to the 'reflection' section of 'reachability-metadata.json'", log):
    start = log.index("{", m.end())
    depth = 0
    for i in range(start, len(log)):
        depth += (log[i] == "{") - (log[i] == "}")
        if depth == 0:
            break
    entry = json.loads(log[start:i + 1])
    old = by_type.get(entry["type"])
    if old is None:
        by_type[entry["type"]] = entry
        added += 1
        continue
    for key, value in entry.items():
        if isinstance(value, list):
            have = old.setdefault(key, [])
            for item in value:
                if item not in have:
                    have.append(item)
                    added += 1
        elif old.get(key) != value:
            old[key] = value
            added += 1
data["reflection"] = list(by_type.values())
target.write_text(json.dumps(data, indent=2))
print(added)
