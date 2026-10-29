#!/usr/bin/env bash
# Spring PetClinic, the Native Image bundle that Graal's benchmark suite ships (spring-petclinic-3.0.1-SNAPSHOT.nib, made in 2023),
# built with the side-effect analysis, one image per configuration, into out/petclinic/<config>/. The bundle is applied with this
# builder; two things it needs that the 2023 builder did not: JMX support (--enable-monitoring=jmxserver) and four registrations
# for reflection (petclinic/reachability-metadata.json, found by petclinic/add-missing-registrations.py: build, run, read what the
# image says it lacks). Every configuration gets both, so the images differ only in what the analysis does.
#
#   graal-native/petclinic.sh graal kills                          # default analysis
#   graal-native/petclinic.sh graalflagscutoff lockscutoff         # allocation sites, cutoff 100: locks removed or not
#
# The configurations are in bundle.sh. `ceiling` does not finish on petclinic: effects.kills was stopped after an hour at 226 GB
# (nearly every one of the 164,600 methods then has a list of tens of thousands of partitions).
#
# The assets are in $PETCLINIC (default ~/eval/petclinic: app/*.nib, workloads/, wrk/, copied from ~/.mx/cache on the laptop).
# petclinic_load.py then starts the images and measures them under load.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"
source "$HERE/provenance.sh"
source "$HERE/bundle.sh"
set +e
PETCLINIC=${PETCLINIC:-$HOME/eval/petclinic}
NIB=$(ls "$PETCLINIC"/app/*.nib)
OUT="$HERE/out/petclinic"
mkdir -p "$OUT"
[[ $# -gt 0 ]] || { echo "usage: petclinic.sh <graal|kills|locks|graalflagscutoff|lockscutoff|ceiling>…" >&2; exit 2; }

# One after the other: builds side by side slow each other down (five at once took 4 to 53 minutes), so their times mean nothing
for config in "$@"; do
    build_bundle "$config" "$NIB" "$OUT/$config" --enable-monitoring=jmxserver -H:ConfigurationFileDirectories="$HERE/petclinic"
done
