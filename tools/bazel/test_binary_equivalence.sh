#!/bin/bash
# Compares every Bazel-built binary against its Make-built counterpart.
#
# Assumes a clean checkout.
set -Eeuo pipefail

trap 'echo "[FAILED] ${BASH_SOURCE[0]}:${LINENO}: ${BASH_COMMAND}" >&2' ERR

repo_root=$(git rev-parse --show-toplevel)
cd "${repo_root}"

BLDENV="${BLDENV:-trixie}"

# rcache, because we don't want this job writing to the shared cache,
# but we can read from the shared cache because we assert a clean build.
# See rules/config for the modes.
CACHE_OPTIONS="${CACHE_OPTIONS:-SONIC_DPKG_CACHE_METHOD=rcache}"

function run_in_slave() {
  # SKIP_SLAVE=1 still runs the command, just on the host. Skipping it outright
  # would make the whole script exit 0 while testing nothing.
  if [[ "${SKIP_SLAVE:-0}" == "1" ]]; then
    eval "$1"
    return
  fi
  make -f Makefile.work "BLDENV=${BLDENV}" sonic-slave-run \
    SONIC_RUN_CMDS="cd /sonic && $1"
}

# Ensure the tree is clean before proceeding.
if [[ -n "$(git status --porcelain)" ]]; then
  if [[ "${ELF_EQUIVALENCE_ALLOW_DIRTY:-0}" != "1" ]]; then
    echo "ERROR: the checkout is dirty. Both sides must come from the same tree." >&2
    git status --short >&2
    echo "Set ELF_EQUIVALENCE_ALLOW_DIRTY=1 to compare anyway." >&2
    exit 1
  fi
  echo "WARNING: comparing on a dirty tree. Results may be inaccurate."
fi

# Invoked directly rather than through `bazel run`, because the script shells out to Bazel itself.
compare="PYTHONPATH=tools/bazel/registry python3 tools/bazel/equivalence_checker/equivalence_checker.py --bldenv ${BLDENV}"

# elfcompare needs abidiff to compare shared libraries, and we haven't migrated abidiff to Bazel yet.
# We need the `tr` because this travels to the slave, so we need to collapse it into one line to fit in a single CLI.
#
# TODO(bazel-ready): Migrate abidiff to Bazel and fetch it from the BCR.
provision_abidiff=$(tr '\n' ' ' <<'EOF'
if ! command -v abidiff >/dev/null; then
  sudo apt-get update &&
    sudo apt-get install -y --no-install-recommends abigail-tools;
fi
EOF
)

# Assert that we're not trying to build with Bazel.
# Otherwise, we'd be comparing Bazel to itself.
if [[ "${BUILD_WITH_BAZEL_WHEN_AVAILABLE:-n}" != "n" ]]; then
  echo "ERROR: BUILD_WITH_BAZEL_WHEN_AVAILABLE must be 'n' here, or Make builds the" >&2
  echo "       container images with Bazel and the comparison proves nothing." >&2
  exit 1
fi

echo "[= Finding the Make artifacts to compare against =]"
make_artifacts_file="target/.equivalence-artifacts"
rm -f "${make_artifacts_file}"
# abidiff is provisioned even here, because the comparison resolves every tool it
# might need up front, before it works out what there is to compare.
run_in_slave "${provision_abidiff} && ${compare} --print-make-paths > ${make_artifacts_file}"
mapfile -t make_artifacts < "${make_artifacts_file}"

if [[ ${#make_artifacts[@]} -eq 0 ]]; then
  echo "ERROR: found no Make artifacts to compare against." >&2
  exit 1
fi

echo "[= Building the Make side =]"
for artifact in "${make_artifacts[@]}"; do
  echo "[make] ${artifact}"
  env ${CACHE_OPTIONS} "BLDENV=${BLDENV}" make "${artifact}"
done

echo "[= Comparing =]"
run_in_slave "${provision_abidiff} && ${compare}"
