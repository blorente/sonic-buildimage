"""Verifies that tools/bazel/submodule-config.bazelrc has an entry for every
module directly under src/ (a real module() call in its own MODULE.bazel) --
whether it's a git submodule or a plain vendored directory.

Run with --fix (via `bazel run`, not `bazel test`) to regenerate the file from scratch:
    bazel run //tools/bazel/registry:submodule_config_test -- --fix
"""

import argparse
import sys

import registry_lib

SUBMODULE_CONFIG = registry_lib.REPO_ROOT / "tools/bazel/submodule-config.bazelrc"


def find_submodule_bazel_modules() -> list[tuple[str, str]]:
    """Return (src_path, module_name) for each src/ module."""
    return sorted(
        (src_path, name) for name, src_path in registry_lib.discover_top_level_bazel_modules()
    )


def find_missing_entries(
    modules: list[tuple[str, str]], config_text: str
) -> list[tuple[str, str]]:
    """Return (submodule_path, module_name) pairs with no `common:unpinned-<name>` stanza."""
    return [
        (submodule_path, name)
        for submodule_path, name in modules
        if f"common:unpinned-{name}" not in config_text
    ]


# submodule-config.bazelrc is only ever imported by a submodule directly under src/
# (e.g. src/sonic-swss-common), so %workspace% is always 2 levels below the repo root
# when these lines are evaluated -- regardless of how deep the overridden module's own
# path is. See the file's header comment for why --registry and --override_module need
# a different ".." count despite both being relative to the same %workspace%.
REGISTRY_DOTS = "../.."
OVERRIDE_MODULE_DOTS = "../../.."


def render_entry(submodule_path: str, name: str) -> str:
    """Render a `common:unpinned-<name>` stanza overriding `name` with `submodule_path`."""
    return f"""
# Override {name} with a local checkout of {submodule_path}.
common:unpinned-{name} --registry=file://%workspace%/{REGISTRY_DOTS}/tools/bazel/registry
common:unpinned-{name} --override_module={name}=%workspace%/{OVERRIDE_MODULE_DOTS}/{submodule_path}
"""


# The full contents of submodule-config.bazelrc, up to the per-module entries, which
# fix() regenerates from scratch every time -- so this is the only place to edit any
# of this text, not the checked-in file.
HEADER = """\
# ==============================================================================
# THIS FILE IS AUTO-GENERATED. Do not hand-edit it -- to add, remove, or refresh
# entries (including this header), run:
#
#     bazel run //tools/bazel/registry:submodule_config_test -- --fix
#
# ==============================================================================
#
# Config file that will be imported by submodules (e.g. src/sonic-swss-common)
# when running under a sonic-buildimage checkout.
# Not to be used by sonic-buildimage directly.
#
# All paths are relative to the root of the submodule that imports this file (%workspace%),
# NOT relative to the module being overridden
#
# For instance, if this file is imported by `sonic-swss-common`, `%workspace%` will be
# `src/sonic-swss-common`, which is 2 levels below the repo root.
#
# This file currently assumes it is only ever imported by a submodule directly under src/
# (2 levels deep, e.g. `src/sonic-swss-common`) -- importing it from a more deeply nested
# submodule (e.g. `src/sonic-sysmgr/gnoi`) would need a different `..` count and is not
# currently supported.
#
# Each override lives under its own --config, named after the module it overrides.
# We cannot just have a big list of modules and override them all with one config,
# because Bazel rejects overriding whichever module is currently root.
#
# So, for instance, if we had `sonic-swss-common` in a unified list, Bazel would crash if we were building in `soinc-swss-common`.
"""


def test_submodule_config_has_entry_for_every_bazel_module_submodule() -> bool:
    """Print a PASS/FAIL report and return whether the file is complete."""
    modules = find_submodule_bazel_modules()
    if not modules:
        print(
            "FAIL: find_submodule_bazel_modules() found no modules under src/ -- "
            "the discovery is broken (this should never legitimately be empty)."
        )
        return False

    missing = find_missing_entries(modules, SUBMODULE_CONFIG.read_text())
    if missing:
        print(f"FAIL: {SUBMODULE_CONFIG} is missing entries for:")
        for submodule_path, name in missing:
            print(f"  - {submodule_path} (module {name!r}, expected 'common:unpinned-{name}')")
        print()
        print("To fix, run:")
        print("    bazel run //tools/bazel/registry:submodule_config_test -- --fix")
        return False

    print("PASS: submodule-config.bazelrc has an entry for every bazel-module submodule")
    return True


def fix() -> None:
    """Regenerate submodule-config.bazelrc from scratch."""
    modules = find_submodule_bazel_modules()
    updated = HEADER + "".join(render_entry(path, name) for path, name in modules)

    if SUBMODULE_CONFIG.exists() and SUBMODULE_CONFIG.read_text() == updated:
        print("Nothing to do: submodule-config.bazelrc is already up to date.")
        return

    SUBMODULE_CONFIG.write_text(updated)
    for submodule_path, name in modules:
        print(f"Wrote common:unpinned-{name} for {submodule_path}")
    print(f"Regenerated {SUBMODULE_CONFIG}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Regenerate submodule-config.bazelrc from scratch.",
    )
    args = parser.parse_args()

    if args.fix:
        fix()
        return

    if not test_submodule_config_has_entry_for_every_bazel_module_submodule():
        sys.exit(1)
    print("All tests passed.")


if __name__ == "__main__":
    main()
