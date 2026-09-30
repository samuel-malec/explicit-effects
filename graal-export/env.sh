#!/usr/bin/env bash
# Override the graal checkout location with GRAAL_HOME.
set -u
G=${GRAAL_HOME:-/home/xmalec/graal}
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -d "$G" ]]; then
    echo "error: graal checkout not found at '$G' (set GRAAL_HOME)" >&2
    exit 1
fi

# Everything the analyzer needs on the classpath. These are jars already built
# in the graal tree -- nothing here builds graal.
CP="$G/substratevm/mxbuild/dists/standalone-pointsto.jar"
CP="$CP:$G/substratevm/mxbuild/dists/pointsto.jar"
CP="$CP:$G/substratevm/mxbuild/dists/native-image-base.jar"
CP="$CP:$G/substratevm/mxbuild/dists/objectfile.jar"
CP="$CP:$G/compiler/mxbuild/dists/hostvmaccess.jar"
CP="$CP:$G/compiler/mxbuild/dists/vmaccess.jar"
CP="$CP:$G/sdk/mxbuild/dists/graal-sdk.jar"
CP="$CP:$G/sdk/mxbuild/dists/nativeimage.jar"
CP="$CP:$G/sdk/mxbuild/dists/collections.jar"
CP="$CP:$G/sdk/mxbuild/dists/word.jar"
CP="$CP:$G/substratevm/mxbuild/dists/svm-shared.jar"
CP="$CP:$G/sdk/mxbuild/dists/vmaccess-guest.jar"
CP="$CP:$G/substratevm/mxbuild/dists/svm-guest-staging.jar"
CP="$CP:$G/substratevm/mxbuild/dists/svm-guest.jar"

for entry in ${CP//:/ }; do
    if [[ ! -f "$entry" ]]; then
        echo "error: missing jar: $entry" >&2
        echo "       the graal tree at '$G' may not be built yet" >&2
        exit 1
    fi
done

# jdk.graal.compiler has to be a named module in the boot layer (the JDK's own
# copy is older than the repo's and lacks the APIs pointsto.jar was built
# against), and its newer split-out dependencies go on the module path.
UPGRADE_MP="$G/compiler/mxbuild/dists/graal.jar"
MODULE_PATH="$G/sdk/mxbuild/dists/collections.jar"
MODULE_PATH="$MODULE_PATH:$G/sdk/mxbuild/dists/word.jar"
MODULE_PATH="$MODULE_PATH:$G/sdk/mxbuild/dists/nativeimage.jar"
MODULE_PATH="$MODULE_PATH:$G/truffle/mxbuild/dists/truffle-compiler.jar"
MODULE_PATH="$MODULE_PATH:$G/compiler/mxbuild/dists/graal-options.jar"
MODULE_PATH="$MODULE_PATH:$G/compiler/mxbuild/dists/graal-management.jar"
ADD_MODULES=org.graalvm.collections,org.graalvm.word,org.graalvm.nativeimage,jdk.graal.compiler.management

CI=jdk.internal.vm.ci
EXPORTS=(
  "--add-modules=$CI"
  "--add-exports=java.base/jdk.internal.module=ALL-UNNAMED"
  "--add-exports=java.base/jdk.internal.misc=ALL-UNNAMED"
  "--add-exports=$CI/jdk.vm.ci.meta=ALL-UNNAMED"
  "--add-exports=$CI/jdk.vm.ci.meta.annotation=ALL-UNNAMED"
  "--add-exports=$CI/jdk.vm.ci.code=ALL-UNNAMED"
  "--add-exports=$CI/jdk.vm.ci.code.site=ALL-UNNAMED"
  "--add-exports=$CI/jdk.vm.ci.code.stack=ALL-UNNAMED"
  "--add-exports=$CI/jdk.vm.ci.common=ALL-UNNAMED"
  "--add-exports=$CI/jdk.vm.ci.runtime=ALL-UNNAMED"
  "--add-exports=$CI/jdk.vm.ci.services=ALL-UNNAMED"
  "--add-exports=$CI/jdk.vm.ci.hotspot=ALL-UNNAMED"
  "--add-exports=$CI/jdk.vm.ci.amd64=ALL-UNNAMED"
  "--add-exports=$CI/jdk.vm.ci.aarch64=ALL-UNNAMED"
)
