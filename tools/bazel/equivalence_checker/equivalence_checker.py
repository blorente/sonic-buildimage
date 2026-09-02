import argparse
import sys
import tempfile
from pathlib import Path

import registry_lib
from collector import collect_artifacts
from comparator import compare_artifacts
from context import Context
from diagnostics import ArtifactIndex, ComparableArtifact, DiagnosticSink
from extractor import extract_all
from tools import Bazel, Tools

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument(
        "--bldenv",
        default="trixie",
        help="Debian release whose Make debs to compare against (slave.mk DEBS_PATH).",
    )
    _ = parser.add_argument(
        "--print-sources",
        action="store_true",
        help="Print the Make artifacts this comparison needs, and exit.",
    )
    _ = parser.add_argument(
        "--print-all-artifacts",
        action="store_true",
        help="Print the artifacts this comparison will check, and exit.",
    )
    _ = parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Assume the Bazel artifacts are already built (they are still located with cquery).",
    )
    _ = parser.add_argument(
        "--report",
        type=Path,
        default=Path("target/equivalence-report.json"),
        help="Where to write the run report, relative to the repo root.",
    )
    args = parser.parse_args()

    build = not (args.skip_build or args.print_sources)

    bazel = Bazel()
    with tempfile.TemporaryDirectory(prefix="equivalence-") as tmp:
        ctx = Context(
                sink = DiagnosticSink(),
                index = ArtifactIndex(),
                bazel = bazel,
                tools = Tools.resolve(bazel),
                needs_build = build,
                debian_release = args.bldenv,
                workdir = Path(tmp),
        )
        return _run(ctx, args)


def _run(ctx: Context, args: argparse.Namespace) -> int:
    source_artifacts = collect_artifacts(ctx)
    if not source_artifacts:
        print("No comparable source_artifacts found.")
        return 1

    if args.print_sources:
        for artifact in source_artifacts:
            print(artifact.printable)
        return 0

    artifacts_to_compare = extract_all(ctx, source_artifacts)

    if args.print_all_artifacts:
        for artifact in artifacts_to_compare:
            print(artifact.printable)
        return 0

    # Compare each artifact, looking at its id, and dispatching: Use compareElf for ELFs (debug and runtime), and use strict file comparison for files.
    compare_artifacts(ctx, artifacts_to_compare)

    # TODO BL: compare each artifact, then hand the outcomes to the reporter.
    print(f"\n{len(artifacts_to_compare)} artifacts to compare")
    for diagnostic in ctx.sink.diagnostics:
        print(f"    {diagnostic.code.code} {diagnostic.artifact}: {diagnostic.msg}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
