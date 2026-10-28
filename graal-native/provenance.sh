#!/usr/bin/env bash
# Which code made a result. Sourced by the scripts that build and run images (after env.sh):
#
#   provenance <directory>     writes <directory>/provenance.txt
#
# For the tool and for the Graal fork: the commit, how many files differ from it and a hash of the difference (a tree copied
# to pontos04 by sync-pontos.sh has no history of its own: it says what it was copied from, in .synced-from). Then the builder
# the images came from, and a warning if the fork's sources are newer than the builder's jars, which means the images do not
# have the changes made since: rebuild with mx.

# The stamp of a tree: the commit, and a hash of the uncommitted changes (tracked files' diff, untracked files' content).
code_stamp() {
    local tree=$1
    echo "commit: $(git -C "$tree" rev-parse HEAD) ($(git -C "$tree" rev-parse --abbrev-ref HEAD)) $(git -C "$tree" log -1 --format=%s)"
    echo "uncommitted: $(git -C "$tree" diff HEAD --name-only | wc -l) tracked files changed, $(git -C "$tree" ls-files --others --exclude-standard | wc -l) untracked"
    echo "diff-sha256: $( { git -C "$tree" diff HEAD; git -C "$tree" ls-files --others --exclude-standard -z | (cd "$tree" && xargs -0 -r sha256sum); } | sha256sum | cut -d' ' -f1)"
}

provenance() {
    local dir=$1 name tree
    mkdir -p "$dir"
    {
        echo "recorded: $(date -Is) on $(hostname)"
        for name in tool fork; do
            [[ $name == tool ]] && tree=$REPO || tree=$G
            if [[ -f $tree/.synced-from ]]; then
                echo "$name, a copy made by sync-pontos.sh ($tree):"
                sed 's/^/    /' "$tree/.synced-from"
            elif git -C "$tree" rev-parse HEAD > /dev/null 2>&1; then
                echo "$name ($tree):"
                code_stamp "$tree" | sed 's/^/    /'
            else
                echo "$name ($tree): no history and no stamp"
            fi
        done
        echo "builder: $(readlink -f "$GRAALVM")"
        local jar newer compiler
        compiler=$(readlink -f "$COMPILER")  # a link into mxbuild
        for jar in "$GRAALVM/lib/svm/builder/svm.jar" "$GRAALVM/lib/svm/builder/pointsto.jar" "$compiler"; do
            [[ -e $jar ]] && echo "    $(basename "$jar"): built $(date -r "$jar" -Is), $(stat -c %s "$jar") bytes"
        done
        newer=$(find "$G/substratevm/src" -name '*.java' -newer "$GRAALVM/lib/svm/builder/svm.jar" 2> /dev/null | head -n 3)
        [[ -z $newer ]] || { echo "WARNING: the fork's sources are newer than the builder's svm.jar, so the images lack those changes (rebuild with mx build):"; echo "$newer" | sed 's/^/    /'; }
        newer=$(find "$G/compiler/src/jdk.graal.compiler/src" -name '*.java' -newer "$compiler" 2> /dev/null | head -n 3)
        [[ -z $newer ]] || { echo "WARNING: the compiler's sources are newer than graal.jar, so the images lack those changes (mx build --dependencies GRAAL in compiler):"; echo "$newer" | sed 's/^/    /'; }
    } > "$dir/provenance.txt"
}
