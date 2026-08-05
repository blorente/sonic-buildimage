"""Verifies that tools/bazel/root-unpinned-modules-config.bazelrc overrides every module
directly under src/ that declares itself as a bazel module.

sonic-buildimage always builds these src/ modules from the checked-out source
tree, regardless of what version any consumer's bazel_dep declares -- see the
file's header comment for why.

Run with --fix (via `bazel run`, not `bazel test`) to regenerate the file from scratch:
    bazel run //tools/bazel/registry:root_config_test -- --fix
"""

import argparse
import sys

import registry_lib

ROOT_CONFIG = registry_lib.REPO_ROOT / "tools/bazel/root-unpinned-modules-config.bazelrc"

# TODO BL: review. Unlike submodule-config.bazelrc, which needs a separate
# --config per module (a submodule can't override itself), root never is one
# of these modules, so all entries share a single config here.
# TODO BL: make sure that bazel test fails if a module is missing, because the traversal fails.
CONFIG_NAME = "local-modules"

# The full contents of root-unpinned-modules-config.bazelrc, up to the per-module entries, which
# fix() regenerates from scratch every time -- so this is the only place to edit
# any of this text, not the checked-in file.
HEADER = """\
# ==============================================================================
# THIS FILE IS AUTO-GENERATED. Do not hand-edit it -- to add, remove, or refresh
# entries (including this header), run:
#
#     bazel run //tools/bazel/registry:root_config_test -- --fix
#
# ==============================================================================
#
# Imported unconditionally by sonic-buildimage's own .bazelrc. Always builds
# these src/ modules from the checked-out tree, regardless of what version any
# consumer's bazel_dep declares -- this bypasses registry lookup and
# version-string resolution entirely (unlike local_path_override(),
# --override_module isn't limited to the root module), so each module's own
# MODULE.bazel is free to declare a real, externally-meaningful pinned version
# instead of a local-only alias.
"""


def find_missing_entries(config_text: str) -> list[tuple[str, str]]:
    """Return (module_name, src_path) pairs with no --override_module entry."""
    return [
        (name, src_path)
        for name, src_path in registry_lib.discover_top_level_bazel_modules()
        if f"--override_module={name}=" not in config_text
    ]


def render_entry(name: str, src_path: str) -> str:
    """Render the override_module stanza for one module."""
    return f"common:{CONFIG_NAME} --override_module={name}=%workspace%/{src_path}\n"


def test_root_config_has_entry_for_every_bazel_module_submodule() -> bool:
    """Print a PASS/FAIL report and return whether the file is complete."""
    missing = find_missing_entries(ROOT_CONFIG.read_text())
    if missing:
        print(f"FAIL: {ROOT_CONFIG} is missing entries for:")
        for name, src_path in missing:
            print(f"  - {src_path} (module {name!r}, expected '--override_module={name}=')")
        print()
        print("To fix, run:")
        print("    bazel run //tools/bazel/registry:root_config_test -- --fix")
        return False

    print("PASS: root-unpinned-modules-config.bazelrc has an entry for every bazel-module submodule")
    return True


def fix() -> None:
    """Regenerate root-unpinned-modules-config.bazelrc from scratch."""
    modules = registry_lib.discover_top_level_bazel_modules()
    updated = HEADER + "".join(render_entry(name, src_path) for name, src_path in modules)

    if ROOT_CONFIG.exists() and ROOT_CONFIG.read_text() == updated:
        print("Nothing to do: root-unpinned-modules-config.bazelrc is already up to date.")
        return

    ROOT_CONFIG.write_text(updated)
    for name, src_path in modules:
        print(f"Wrote --override_module={name}= for {src_path}")
    print(f"Regenerated {ROOT_CONFIG}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Regenerate root-unpinned-modules-config.bazelrc from scratch.",
    )
    args = parser.parse_args()

    if args.fix:
        fix()
        return

    if not test_root_config_has_entry_for_every_bazel_module_submodule():
        sys.exit(1)
    print("All tests passed.")


if __name__ == "__main__":
    main()
