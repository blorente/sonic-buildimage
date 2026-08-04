#!/usr/bin/env python3
"""Publish git-submodule-backed Bazel modules to the remote sonic-bazel-registry.

Scans src/ for MODULE.bazel files belonging to git submodules,
and publishes any not-yet-published (module, version+commit) pairs to
https://github.com/blorente/sonic-bazel-registry as a PR.

TODO: Migrate to sonic-net when we have a repository available.

Usage:
    python3 tools/bazel/registry/publish_to_remote_registry.py
"""

import base64
import difflib
import hashlib
import json
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import click

from registry_lib import (
    REPO_ROOT,
    is_git_submodule,
    load_submodule_paths,
    load_submodule_urls,
    parse_module_declaration,
    rewrite_module_version,
    submodule_root_for,
)

REGISTRY_REPO_URL = "https://github.com/blorente/sonic-bazel-registry"


def check_repo_is_clean() -> None:
    """Abort if sonic-buildimage (including submodules) has uncommitted changes."""
    result = subprocess.run(
        ["git", "status", "--porcelain", "--ignore-submodules=none"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    if result.stdout.strip():
        raise click.ClickException(
            "Repo has uncommitted changes; commit or stash them before publishing:\n"
            + result.stdout
        )


def discover_submodule_modules() -> list[tuple[str, str, str]]:
    """Find MODULE.bazel files that live inside git submodules.

    Returns a list of (name, version, src_path), where src_path is relative
    to the repo root (e.g. "src/sonic-sysmgr").
    """
    submodule_paths = load_submodule_paths()
    modules = []

    for module_bazel in sorted((REPO_ROOT / "src").rglob("MODULE.bazel")):
        src_path = str(module_bazel.parent.relative_to(REPO_ROOT))
        if not is_git_submodule(src_path, submodule_paths):
            continue
        result = parse_module_declaration(module_bazel)
        if result is None:
            continue
        name, version = result
        modules.append((name, version, src_path))

    return modules


def resolve_commit(src_path: str) -> str:
    """Return the full 40-char SHA of the submodule's currently checked-out commit."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT / src_path,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def parse_github_org_repo(url: str) -> tuple[str, str]:
    """Extract (org, repo) from a github.com submodule URL.

    Fails fast if the URL isn't a github.com URL,
    since archive-based publishing only knows how to build github.com archive URLs.
    """
    match = re.match(r"^https://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", url)
    if match is None:
        raise click.ClickException(f"Unsupported submodule remote (not a github.com URL): {url}")
    return match.group(1), match.group(2)


def compute_archive_integrity(archive_url: str) -> str:
    """Download the archive at archive_url and return its Bazel-style sha256 integrity string."""
    try:
        with urllib.request.urlopen(archive_url) as response:
            archive_bytes = response.read()
    except urllib.error.HTTPError as e:
        raise click.ClickException(
            f"Could not download {archive_url} ({e.code} {e.reason}). "
            "The pinned commit is likely missing from the submodule's registered remote "
            "(check .gitmodules) — push it there before publishing."
        ) from e
    digest = hashlib.sha256(archive_bytes).digest()
    return "sha256-" + base64.b64encode(digest).decode("ascii")


def clone_registry() -> Path:
    """Clone the remote registry repo into a fresh temp directory.

    Works even if the remote repo has no commits yet (git clone of an empty
    repo succeeds; it just leaves the checkout with no branch/HEAD).
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="sonic-bazel-registry-"))
    subprocess.run(
        ["git", "clone", REGISTRY_REPO_URL, str(tmp_dir)],
        capture_output=True,
        text=True,
        check=True,
    )
    return tmp_dir


def is_already_published(registry_dir: Path, name: str, target_version: str) -> bool:
    """Check whether modules/<name>/<target_version>/ already exists in the registry clone."""
    return (registry_dir / "modules" / name / target_version).is_dir()


def update_metadata(registry_dir: Path, name: str, target_version: str) -> None:
    """Add target_version to modules/<name>/metadata.json, preserving existing versions."""
    metadata_path = registry_dir / "modules" / name / "metadata.json"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text())
    else:
        metadata = {"versions": []}

    if target_version not in metadata["versions"]:
        metadata["versions"] = sorted(metadata["versions"] + [target_version])

    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")


def build_version_patch(original_text: str, new_version: str) -> tuple[str, str]:
    """Return (patch_text, patched_text) that bumps the module()'s version field.

    Follows the BCR convention, where the checked-in MODULE.bazel
    must match the result of applying the registry patches to a given module archive.
    """
    patched_text = rewrite_module_version(original_text, new_version)
    patch_text = "".join(
        difflib.unified_diff(
            original_text.splitlines(keepends=True),
            patched_text.splitlines(keepends=True),
            fromfile="a/MODULE.bazel",
            tofile="b/MODULE.bazel",
        )
    )
    return patch_text, patched_text


def write_module_entry(
    registry_dir: Path, name: str, target_version: str, src_path: str, source_json: dict
) -> None:
    """Write source.json, a version-bumped MODULE.bazel, its patch, and metadata.json."""
    version_dir = registry_dir / "modules" / name / target_version
    version_dir.mkdir(parents=True)

    original_text = (REPO_ROOT / src_path / "MODULE.bazel").read_text()
    patch_text, patched_text = build_version_patch(original_text, target_version)

    patch_name = "bump-version.patch"
    (version_dir / "patches").mkdir()
    (version_dir / "patches" / patch_name).write_text(patch_text)
    patch_integrity = "sha256-" + base64.b64encode(hashlib.sha256(patch_text.encode()).digest()).decode("ascii")

    source_json = {**source_json, "patches": {patch_name: patch_integrity}, "patch_strip": 1}
    (version_dir / "source.json").write_text(json.dumps(source_json, indent=2) + "\n")
    (version_dir / "MODULE.bazel").write_text(patched_text)

    update_metadata(registry_dir, name, target_version)


def commit_changes(registry_dir: Path, published: list[tuple[str, str]]) -> str:
    """Create a branch and commit all newly-written module files. Returns the branch name."""
    branch_name = "publish/" + datetime.now().strftime("%Y%m%d-%H%M%S")
    message = "Publish " + ", ".join(f"{name} {version}" for name, version in published)

    subprocess.run(
        ["git", "checkout", "-b", branch_name], cwd=registry_dir, check=True, capture_output=True, text=True
    )
    subprocess.run(["git", "add", "-A"], cwd=registry_dir, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", message], cwd=registry_dir, check=True, capture_output=True, text=True
    )
    return branch_name


def push_and_create_pr(registry_dir: Path, branch_name: str, published: list[tuple[str, str]]) -> str:
    """Push branch_name and open a PR against the registry repo. Returns the PR URL."""
    subprocess.run(
        ["git", "push", "-u", "origin", branch_name],
        cwd=registry_dir,
        check=True,
        capture_output=True,
        text=True,
    )

    title = "Publish " + ", ".join(f"{name}" for name, _ in published)
    body = "Published modules:\n" + "\n".join(f"- {name} {version}" for name, version in published)

    result = subprocess.run(
        ["gh", "pr", "create", "--title", title, "--body", body, "--head", branch_name],
        cwd=registry_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@click.command()
def main() -> None:
    """Publish git-submodule-backed modules to the remote registry."""
    check_repo_is_clean()

    modules = discover_submodule_modules()

    if not modules:
        print("No git-submodule-backed modules found under src/")
        return

    submodule_paths = load_submodule_paths()
    submodule_urls = load_submodule_urls()

    candidates = []
    for name, version, src_path in modules:
        root = submodule_root_for(src_path, submodule_paths)
        org, repo = parse_github_org_repo(submodule_urls[root])
        commit = resolve_commit(src_path)
        target_version = f"{version}-{commit}"
        candidates.append((name, target_version, src_path, org, repo, commit))

    registry_dir = clone_registry()
    print(f"Cloned {REGISTRY_REPO_URL} to {registry_dir}")

    published = []
    for name, target_version, src_path, org, repo, commit in candidates:
        if is_already_published(registry_dir, name, target_version):
            print(f"skip (already published): {name} {target_version}")
            continue

        archive_url = f"https://github.com/{org}/{repo}/archive/{commit}.tar.gz"
        source_json = {
            "url": archive_url,
            "strip_prefix": f"{repo}-{commit}",
            "integrity": compute_archive_integrity(archive_url),
        }
        write_module_entry(registry_dir, name, target_version, src_path, source_json)
        published.append((name, target_version))
        print(f"new: {name} {target_version}")

    if not published:
        print("Nothing new to publish.")
        return

    branch_name = commit_changes(registry_dir, published)
    pr_url = push_and_create_pr(registry_dir, branch_name, published)
    print(f"Opened PR: {pr_url}")


if __name__ == "__main__":
    main()
