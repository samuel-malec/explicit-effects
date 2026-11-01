#!/usr/bin/env bash
# Mirror the working trees of the tool and of the Graal fork to pontos04, so that what runs there is what is here: a file
# removed here is removed there too (a stale src/rules would otherwise stay), generated output (out/, mxbuild/, .venv/) is
# left alone, and each tree gets a stamp, .synced-from, saying which commit it was made from and a hash of what differs
# from that commit. provenance.sh writes the stamps next to every run's output, so a number traces to a code state even
# when the state was not committed.
#
#   scripts/server/sync-pontos.sh --dry-run     # what would be copied and removed
#   scripts/server/sync-pontos.sh               # do it
#   scripts/server/sync-pontos.sh --dry-run tool    # only the tool (or: fork)
#
# After the fork's sources changed: ssh pontos04 'cd ~/graal/substratevm && mx build' (it builds the builder jars the runs use).
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../../graal-native/env.sh"
source "$HERE/provenance.sh"
set +e
REMOTE=${REMOTE:-pontos04.fi.muni.cz}
# Files are compared by content, not by size and time: the copies there were made at other times, and a number must not depend on that.
# FAST=1 compares by size and time, for a repeated sync after a first one.
COMPARE=(--checksum)
[[ -z ${FAST:-} ]] || COMPARE=()
DRY=()
WHICH=()
for argument in "$@"; do
    case $argument in
        --dry-run) DRY=(--dry-run) ;;
        tool|fork) WHICH+=("$argument") ;;
        *) echo "usage: sync-pontos.sh [--dry-run] [tool] [fork]" >&2; exit 2 ;;
    esac
done
[[ ${#WHICH[@]} -gt 0 ]] || WHICH=(tool fork)

mirror() {
    local name=$1 source=$2 target=$3
    shift 3
    echo "== $name: $source -> $REMOTE:$target ${DRY[*]}"
    # What git ignores (build output, caches, the IDE's files) is neither sent nor deleted over there.
    local ignored changes
    ignored=$(mktemp)
    git -C "$source" ls-files --others --ignored --exclude-standard --directory | sed 's|^|/|' > "$ignored"
    changes=$(rsync -a "${COMPARE[@]}" --delete --itemize-changes "${DRY[@]}" --filter='H __pycache__/' --filter='H *.pyc' --exclude-from="$ignored" "$@" "$source/" "$REMOTE:$target/" | grep -v '^\.')
    rm -f "$ignored"
    echo "$changes" | grep 'deleting' | sed 's/^/   /'
    echo "   $(echo "$changes" | grep -c '^<f') files copied (new or changed), $(echo "$changes" | grep -c 'deleting') removed"
    echo "$changes" | grep '^<f' | grep -v '^<f\.\.t' | sed -n 1,40p | sed 's/^/   changed: /'
    if [[ ${#DRY[@]} -eq 0 ]]; then
        { echo "synced: $(date -Is) from $(hostname):$source"; code_stamp "$source"; } | ssh "$REMOTE" "cat > $target/.synced-from"
        echo "   stamp: $(code_stamp "$source" | sed -n 1,2p | tr '\n' ' ')"
    fi
}

for which in "${WHICH[@]}"; do
    case $which in
        tool)
            mirror "tool" "$REPO" explicit-effects \
                --exclude='/.git' --exclude='/.venv/' --exclude='/.idea/' --exclude='/.notes/' --exclude='/.pytest_cache/' --exclude='/.ruff_cache/' \
                --exclude='/graal/' --exclude='/are-we-fast-yet/' --exclude='/thesis/' \
                --exclude='/graal-export/out/' --exclude='/graal-export/classes/' --exclude='/graal-export/*.class' \
                --exclude='/graal-native/out/' --exclude='/programs/awfy/classes/' --exclude='.synced-from'
            ;;
        fork)
            mirror "fork" "$G" graal \
                --exclude='/.git' --exclude='.idea/' --exclude='mxbuild/' --exclude='latest_graalvm_home' --exclude='.mx.*' \
                --exclude='.synced-from'
            ;;
    esac
done
