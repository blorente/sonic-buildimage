#!/usr/bin/env python3
"""Generate a local Bazel registry from sonic-buildimage submodules.

Scans src/ for MODULE.bazel files, extracts each module's name and version,
then creates the registry directory structure under tools/bazel/registry/modules/.

Usage:
    python3 tools/bazel/registry/generate_registry.py
"""

import json
import os
import shutil
from pathlib import Path

import click

from registry_lib import REPO_ROOT, is_git_submodule, load_submodule_paths, parse_module_declaration

MODULES_DIR = Path(__file__).resolve().parent / "modules"
LOCAL_VERSION_SUFFIX = ".sonic-buildimage"


def discover_modules() -> list[tuple[str, str, str]]:
    """Find all MODULE.bazel files under src/ and return (name, version, path).

    The path is relative to the repo root (e.g. "src/sonic-swss-common").

    Modules that resolve locally to sonic-buildimage itself (i.e. their
    directory under src/ is not a git submodule) have LOCAL_VERSION_SUFFIX
    appended to their version, so they can't collide with the same module
    name/version published from its own upstream repo.
    """
    modules = []
    src_dir = REPO_ROOT / "src"
    submodule_paths = load_submodule_paths()

    for module_bazel in sorted(src_dir.rglob("MODULE.bazel")):
        result = parse_module_declaration(module_bazel)
        if result is None:
            continue
        name, version = result
        src_path = str(module_bazel.parent.relative_to(REPO_ROOT))
        if not is_git_submodule(src_path, submodule_paths) and not version.endswith(
            LOCAL_VERSION_SUFFIX
        ):
            version += LOCAL_VERSION_SUFFIX
        modules.append((name, version, src_path))

    return modules


def generate_module_entry(name: str, version: str, src_path: str) -> None:
    """Create registry files for one module."""
    version_dir = MODULES_DIR / name / version
    version_dir.mkdir(parents=True, exist_ok=True)

    # metadata.json
    metadata = MODULES_DIR / name / "metadata.json"
    metadata.write_text(json.dumps({"versions": [version]}, indent=2) + "\n")

    # source.json
    source = version_dir / "source.json"
    source.write_text(
        json.dumps({"type": "local_path", "path": src_path}, indent=2) + "\n"
    )

    # MODULE.bazel — relative symlink so it works on any machine
    src_module = REPO_ROOT / src_path / "MODULE.bazel"
    dst_module = version_dir / "MODULE.bazel"
    rel_target = os.path.relpath(src_module, version_dir)
    dst_module.symlink_to(rel_target)


@click.command()
def main() -> None:
    """Generate a local Bazel registry from sonic-buildimage submodules."""
    modules = discover_modules()

    if not modules:
        raise click.ClickException("No modules found under src/")

    # Only remove generated (symlinked) entries; preserve manually-committed
    # ones like rules_go which contain real content (tarballs, patches).
    if MODULES_DIR.exists():
        for entry in MODULES_DIR.iterdir():
            if not entry.is_dir():
                continue
            is_generated = False
            for version_dir in entry.iterdir():
                if not version_dir.is_dir():
                    continue
                module_file = version_dir / "MODULE.bazel"
                if module_file.is_symlink():
                    is_generated = True
                    break
            if is_generated:
                shutil.rmtree(entry)

    for name, version, path in modules:
        generate_module_entry(name, version, path)

    print(f"Generated registry for {len(modules)} modules in {MODULES_DIR}")
    for name, version, path in modules:
        print(f"  {name} {version} -> {path}")


if __name__ == "__main__":
    main()
