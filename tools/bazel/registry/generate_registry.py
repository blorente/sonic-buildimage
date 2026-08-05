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

import click

from registry_lib import (
    MODULES_DIR,
    REPO_ROOT,
    parse_module_declaration,
    rewrite_module_version,
)

# Every module in the local registry is forced to this version, regardless of
# whatever its own module() call declares. This lets any consumer depend on
# e.g. sonic-build-infra@9999.99.99.sonic-buildimage unconditionally, without
# tracking that module's actual current version -- and since it's a very
# high version number, MVS always resolves to this locally registered copy
# over any other version requested elsewhere in the graph.
LOCAL_ALIAS_VERSION = "9999.99.99"
LOCAL_VERSION_SUFFIX = ".sonic-buildimage"

# Written into every generated version_dir, so main()'s cleanup pass can tell
# generated entries apart from manually-committed ones (e.g. rules_go) even
# when the MODULE.bazel inside isn't a symlink -- see generate_module_entry.
GENERATED_MARKER = ".generated"


def discover_modules() -> list[tuple[str, str, str]]:
    """Find all MODULE.bazel files under src/ and return (name, version, path).

    The path is relative to the repo root (e.g. "src/sonic-swss-common").
    version is always LOCAL_ALIAS_VERSION + LOCAL_VERSION_SUFFIX; see the
    module comment on LOCAL_ALIAS_VERSION.
    """
    modules = []
    src_dir = REPO_ROOT / "src"
    version = LOCAL_ALIAS_VERSION + LOCAL_VERSION_SUFFIX

    for module_bazel in sorted(src_dir.rglob("MODULE.bazel")):
        result = parse_module_declaration(module_bazel)
        if result is None:
            continue
        name, _ = result
        src_path = str(module_bazel.parent.relative_to(REPO_ROOT))
        modules.append((name, version, src_path))

    return modules


def generate_module_entry(name: str, version: str, src_path: str) -> None:
    """Create registry files for one module."""
    version_dir = MODULES_DIR / name / version
    version_dir.mkdir(parents=True, exist_ok=True)
    (version_dir / GENERATED_MARKER).touch()

    # metadata.json
    metadata = MODULES_DIR / name / "metadata.json"
    metadata.write_text(json.dumps({"versions": [version]}, indent=2) + "\n")

    # source.json
    source = version_dir / "source.json"
    source.write_text(
        json.dumps({"type": "local_path", "path": src_path}, indent=2) + "\n"
    )

    # MODULE.bazel: Bazel requires the version declared inside the file to
    # exactly match the registered version (it errors with "the MODULE.bazel
    # file of X@Y declares a different version" otherwise), so a plain
    # symlink only works when the source's own declared version already
    # matches (e.g. real submodules). When it doesn't -- e.g. LOCAL_VERSION_SUFFIX
    # was appended -- write a real copy with the version field rewritten instead.
    src_module = REPO_ROOT / src_path / "MODULE.bazel"
    dst_module = version_dir / "MODULE.bazel"
    if dst_module.is_symlink() or dst_module.exists():
        dst_module.unlink()

    _, raw_version = parse_module_declaration(src_module)
    if raw_version == version:
        rel_target = os.path.relpath(src_module, version_dir)
        dst_module.symlink_to(rel_target)
    else:
        dst_module.write_text(rewrite_module_version(src_module.read_text(), version))


@click.command()
def main() -> None:
    """Generate a local Bazel registry from sonic-buildimage submodules."""
    modules = discover_modules()

    if not modules:
        raise click.ClickException("No modules found under src/")

    # Only remove generated entries (marked with GENERATED_MARKER); preserve
    # manually-committed ones like rules_go which contain real content
    # (tarballs, patches).
    if MODULES_DIR.exists():
        for entry in MODULES_DIR.iterdir():
            if not entry.is_dir():
                continue
            is_generated = any(
                (version_dir / GENERATED_MARKER).exists()
                for version_dir in entry.iterdir()
                if version_dir.is_dir()
            )
            if is_generated:
                shutil.rmtree(entry)

    for name, version, path in modules:
        generate_module_entry(name, version, path)

    print(f"Generated registry for {len(modules)} modules in {MODULES_DIR}")
    for name, version, path in modules:
        print(f"  {name} {version} -> {path}")


if __name__ == "__main__":
    main()
