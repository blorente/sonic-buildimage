import argparse
import sys
import tempfile
from pathlib import Path

import registry_lib
from collector import collect_artifacts
from context import Context
from diagnostics import ArtifactIndex, DiagnosticSink
from tools import Bazel, Tools

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument(
        "--bldenv",
        default="trixie",
        help="Debian release whose Make debs to compare against (slave.mk DEBS_PATH).",
    )
    _ = parser.add_argument(
        "--print-artifacts",
        action="store_true",
        help="Print the Make artifacts this comparison needs, one relative path per line, and exit.",
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

    # Naming the debs only needs analysis, not execution.
    build = not (args.skip_build or args.print_artifacts)

    bazel = Bazel()
    ctx = Context(
            sink = DiagnosticSink(),
            index = ArtifactIndex(),
            bazel = bazel,
            tools = Tools.resolve(bazel),
            needs_build = build,
            debian_release = args.bldenv,
    )

    artifacts = collect_artifacts(ctx)
    if not artifacts:
        print("No comparable artifacts found.")
        return 1

    if args.print_artifacts:
        for artifact in artifacts:
            print(f"{artifact.type} {artifact.identifier}")
            print(f"    bazel: {artifact.bazelVersion.relative_to(registry_lib.REPO_ROOT)}")
            print(f"    make:  {artifact.makeVersion.relative_to(registry_lib.REPO_ROOT)}")
        return 0

    by_module = collect_pairs(args.bldenv, build=build)

    with tempfile.TemporaryDirectory(prefix="elf-equivalence-") as tmp:
        for module, pairs in by_module.items():
            print(f"=== {module} ===")
            make, bazel = extract_module(module, pairs, ctx.tools, reporter, Path(tmp))
            if make is None or bazel is None:
                continue
            compare_module(module, make, bazel, ctx.tools, reporter)

    report = registry_lib.REPO_ROOT / args.report
    reporter.write_report(report)
    status = reporter.summarise()
    print(f"\nReport: {report.relative_to(registry_lib.REPO_ROOT)}")
    return status

if __name__ == "__main__":
    sys.exit(main())
