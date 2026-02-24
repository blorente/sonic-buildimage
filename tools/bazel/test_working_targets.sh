#!/bin/bash
set -euo pipefail

repo_root=$(git rev-parse --show-toplevel)

function test_repo() {
  repo=$1
  cmd=$2
  echo "[test] ${repo}: ${cmd}"
  pushd "${repo_root}/${repo}"
  ${cmd}
  popd
}

echo "[= Testing Dependent Repositories =]"

test_repo "../sonic-utilities" "bazel build :sonic-utilities :dist"
test_repo "../sonic-host-services" "bazel build :sonic-host-services :dist"
test_repo "../sonic-sairedis/SAI" "bazel build ..."
test_repo "../sonic-sairedis" "bazel build ..."
test_repo "../sonic-dash-api" "bazel build ..."
test_repo "../sonic-swss-common" "bazel build ..."
test_repo "../sonic-swss" "bazel build ..."
test_repo "../sonic-pins" "bazel build ..."
test_repo "../sonic-build-infra" "bazel build ..."

echo "[= Testing Docker Images =]"

cd "${repo_root}"
bazel query 'kind(oci_load, ...)'

# for load in $(bazel query 'kind(oci_load, ...)'); do
for load in $(bazel query 'kind(oci_load, ...) - //dockers/docker-sonic-p4rt:load'); do
    echo "[load] ${load}"
    bazel run "${load}"
done

echo "[= DONE =]"
