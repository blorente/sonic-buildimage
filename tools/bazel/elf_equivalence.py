"""Checks that Bazel-built binaries are semantically equivalent to Make-built ones.

Pairing works at two levels:
  * Debs pair by filename. In Bazel, `sonic_deb` emits `<package>_<version>_<arch>.deb`,
    which is the Debian convention Make already follows.
  * ELFs inside a deb pair by install path.
  * Debug files are indexed by build-id and reached through the runtime binary that owns them.
"""

import argparse
import collections
import dataclasses
import enum
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import elf_equivalence_rules as rules
import registry_lib

# `sonic_deb` is a symbolic macro, so we have to query on the actual name of the rule.
DEB_RULE_KIND = "_sonic_deb_assemble rule"

EXCLUDE_TAG = "no-elf-equivalence"

READELF_LABEL = "@sonic_build_infra//toolchains/binutils:readelf"
ELFCOMPARE_LABEL = "@compare_elf//:elfcompare"
QUERY_FLAGS = ["--keep_going", "--noshow_progress", "--ui_event_filters=-INFO,-WARNING"]

BUILD_ID_RE = re.compile(r"Build ID:\s*([0-9a-f]+)")

# elfcompare's exit statuses.
EXIT_CLEAN = 0
EXIT_DIFFERENT = 1
EXIT_UNPARSEABLE = 2
EXIT_INCOMPLETE = 3

# Debug files live at /usr/lib/debug/.build-id/NN/REST.debug.
DEBUG_PREFIX = "/usr/lib/debug/.build-id/"


class Verdict(enum.StrEnum):
    """How one artifact pair came out.

    EQUIVALENT is the only passing verdict.
    `Reporter.summarise` counts everything else as a failure.
    """

    EQUIVALENT = "EQUIVALENT"
    DIFFERENT = "DIFFERENT"
    # Only one side retains .symtab, so no verdict is possible.
    ASYMMETRIC = "ASYMMETRIC"
    INCOMPLETE = "INCOMPLETE"
    UNPARSEABLE = "UNPARSEABLE"
    ERROR = "ERROR"
    MAKE_ONLY = "MAKE-ONLY"
    BAZEL_ONLY = "BAZEL-ONLY"
    NO_DEBUG = "NO-DEBUG"

    # There are differences, but we have looked at them and decided to accept them.
    ACCEPTED = "ACCEPTED"
    # We checked less than we could, but we accept that as benign.
    ACCEPTED_BUT_INCOMPLETE = "ACCEPTED-BUT-INCOMPLETE"

    NO_MAKE_DEB = "NO-MAKE-DEB"


# A downgraded coverage gap is reported apart from a downgraded difference.
COVERAGE_GAPS = frozenset(
    {Verdict.INCOMPLETE, Verdict.ASYMMETRIC, Verdict.NO_DEBUG}
)

# Assert that every DowngradableVerdict is a Verdict
_DOWNGRADABLE = {v.value for v in rules.DowngradableVerdict}
if not _DOWNGRADABLE <= {v.value for v in Verdict}:
    raise ValueError(
        "DowngradableVerdict names verdicts that do not exist: "
        f"{sorted(_DOWNGRADABLE - {v.value for v in Verdict})}"
    )

# Assert that every verdict that can result in a coverage gap is a DowngradableVerdict
if not {v.value for v in COVERAGE_GAPS} <= _DOWNGRADABLE:
    raise ValueError(
        "coverage gaps that no rule can accept: "
        f"{sorted({v.value for v in COVERAGE_GAPS} - _DOWNGRADABLE)}"
    )

# Verdicts that do not fail the run.
PASSING = frozenset(
    {Verdict.EQUIVALENT, Verdict.ACCEPTED, Verdict.ACCEPTED_BUT_INCOMPLETE}
)


# elfcompare's exit status -> (verdict, detail).
ELFCOMPARE_VERDICTS: dict[int, tuple[Verdict, str]] = {
    EXIT_CLEAN: (Verdict.EQUIVALENT, ""),
    EXIT_DIFFERENT: (Verdict.DIFFERENT, ""),
    EXIT_UNPARSEABLE: (Verdict.UNPARSEABLE, "elfcompare could not read an artifact"),
    EXIT_INCOMPLETE: (Verdict.INCOMPLETE, "part of the analysis did not run"),
}


@dataclasses.dataclass(frozen=True)
class DebPair:
    """One deb as each build system produces it.

    The two sides pair by filename, so `make` and `bazel` are the same
    `<package>_<version>_<arch>.deb` built two ways.
    """

    label: str
    make: Path
    bazel: Path


@dataclasses.dataclass(frozen=True)
class Tool:
    """An external program this script shells out to."""

    name: str
    argv: tuple[str, ...]

    def run(
        self,
        *args: str,
        check: bool = True,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess:
        """Run the tool. `check` is off for tools whose exit status is a verdict."""
        return subprocess.run(
            [*self.argv, *args],
            cwd=registry_lib.REPO_ROOT,
            capture_output=True,
            text=True,
            check=check,
            env=os.environ | {"LC_ALL": "C"} | (env or {}),
        )

    @property
    def command_line(self) -> str:
        """The command, quoted for passing through the environment."""
        return shlex.join(self.argv)

    @classmethod
    def from_command(cls, name: str, argv: list[str]) -> "Tool":
        """A tool invoked as `argv`, with its first word resolved through PATH.

        A tool that is not installed is reported here, before any comparison
        work happens.
        """
        executable = shutil.which(argv[0])
        if executable is None:
            raise SystemExit(
                f"{name}: '{argv[0]}' is not on PATH. Install it, or put it on "
                "PATH, and re-run."
            )
        return cls(name, (executable, *argv[1:]))

    @classmethod
    def from_bazel(cls, name: str, label: str) -> "Tool":
        """The executable that building `label` produces.

        Because we use some tools with Bazel (e.g. readelf),
        using actual `bazel run` would create a Bazel-in-Bazel problem if compare_elf calls Bazel.
        This would create a deadlock when the second `bazel run` tries to acquire the workspace lock.
        """

        executable = _bazel_output_artifact(
            label,
            ["--output=starlark", "--starlark:expr=target.files_to_run.executable.path"],
        )
        return cls(name, (str(executable),))


@dataclasses.dataclass(frozen=True)
class Tools:
    """Every external program the comparison needs."""

    readelf: Tool
    abidiff: Tool
    elfcompare: Tool
    dpkg_deb: Tool

    @classmethod
    def resolve(cls) -> "Tools":
        return cls(
            readelf=Tool.from_bazel("readelf", READELF_LABEL),
            abidiff=Tool.from_command("abidiff", ["abidiff"]),
            elfcompare=Tool.from_bazel("elfcompare", ELFCOMPARE_LABEL),
            dpkg_deb=Tool.from_command("dpkg-deb", ["dpkg-deb"]),
        )


def _bazel(
    *args: str,
    cwd: Path | None = None,
    ok_statuses: tuple[int, ...] = (0,),
) -> subprocess.CompletedProcess:
    """Run one bazel command, in the repo root unless `cwd` says otherwise."""
    result = subprocess.run(
        ["bazel", *args],
        cwd=cwd or registry_lib.REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode not in ok_statuses:
        raise RuntimeError(
            f"bazel {args[0]} failed in {result.args} (exit {result.returncode}):\n"
            f"{result.stderr}"
        )
    return result


def _lines(result: subprocess.CompletedProcess) -> list[str]:
    """The non-empty stdout lines of a completed command."""
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _query(module_dir: Path, expression: str) -> list[str]:
    """Run one `bazel query` in `module_dir`, returning the labels it printed.

    --keep_going makes a partial failure exit 3 with usable results on stdout, so
    only a harder status is worth failing on.
    """
    return _lines(
        _bazel("query", *QUERY_FLAGS, expression, cwd=module_dir, ok_statuses=(0, 3))
    )


def query_deb_targets(module_dir: Path) -> tuple[list[str], list[str]]:
    """Return (compared, excluded) deb labels declared by the module at `module_dir`."""
    all_debs = _query(module_dir, f'kind("{DEB_RULE_KIND}", //...)')
    excluded = _query(
        module_dir,
        f'attr(tags, "{EXCLUDE_TAG}", kind("{DEB_RULE_KIND}", //...))',
    )
    return sorted(set(all_debs) - set(excluded)), sorted(excluded)


def root_repo_names() -> dict[str, str]:
    """Map Bazel module name -> the repo name it is visible as from the root workspace.

    The mapping comes from Bazel, so it is what module resolution actually
    produced: repo_name defaults, transitive visibility and all.
    """
    result = _bazel("mod", "dump_repo_mapping", "")
    return {
        # A module's canonical repo name is `<module name>+`. Every other shape
        # belongs to a module extension or a repo rule, which has no module.
        #
        # TODO(bazel-ready): We tolerate an instance of canonical repo naming here,
        # because it's more stable than the alternative (parsing MODULE.bazel files directly).
        canonical.removesuffix("+"): apparent
        for apparent, canonical in json.loads(result.stdout).items()
        if canonical.endswith("+") and canonical.count("+") == 1
    }


def _bazel_output_artifact(
    label: str, output: list[str], build: bool = True
) -> Path:
    """The one path `label` yields under `output`, as built from the root workspace.
    """
    if build:
        _bazel("build", "--noshow_progress", label)
    paths = _lines(_bazel("cquery", *QUERY_FLAGS, *output, label))
    if len(paths) != 1:
        raise RuntimeError(f"{label} has {len(paths)} outputs, expected exactly 1")
    return registry_lib.REPO_ROOT / paths[0]



def bazel_output_file(label: str, build: bool = True) -> Path:
    """The single file `label` produces, as built from the root workspace.

    `build=False` locates the file without producing it, for callers that only need its name.
    """
    return _bazel_output_artifact(label, ["--output=files"], build=build)


def has_symtab(elf: Path, readelf: Tool) -> bool:
    """True if `elf` still carries .symtab.

    Useful to detect drift in stripping options.
    """
    return " .symtab" in readelf.run("-S", str(elf)).stdout


@dataclasses.dataclass
class Outcome:
    """What one artifact came to, and the findings behind it."""

    artifact: str
    verdict: Verdict
    detail: str
    findings: list[dict] = dataclasses.field(default_factory=list)


class Reporter:
    """Accumulates per-pair outcomes and renders the final verdict."""

    def __init__(self) -> None:
        self.outcomes: list[Outcome] = []
        # Rule id -> how many findings and verdicts it accepted.
        self.accepted_by: collections.Counter[str] = collections.Counter()

    def credit(self, rule_id: str, count: int = 1) -> None:
        """Record that `rule_id` accepted `count` things."""
        self.accepted_by[rule_id] += count

    def record(
        self,
        artifact: rules.Artifact | str,
        verdict: Verdict,
        detail: str,
        findings: list[dict] | None = None,
    ) -> None:
        assert isinstance(artifact, rules.Artifact) or verdict is Verdict.NO_MAKE_DEB, (
            f"{verdict} must name an Artifact, not {artifact!r}"
        )
        self.outcomes.append(Outcome(str(artifact), verdict, detail, findings or []))
        print(f"    {verdict} {artifact}")
        if detail:
            print(f"        {detail}")

    def write_report(self, path: Path) -> None:
        """Write the whole run, including which rule accepted what.

        The findings can be recovered by re-running elfcompare; the acceptance
        decisions only exist during a run.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "outcomes": [dataclasses.asdict(o) for o in self.outcomes],
                    "accepted_by": dict(self.accepted_by),
                },
                indent=2,
            )
        )

    def summarise(self) -> int:
        print()
        for rule in rules.RULES:
            print(f"    rule {rule.id}: {self.accepted_by[rule.id]} accepted")
        print()
        counts = collections.Counter(o.verdict for o in self.outcomes)
        for verdict, count in sorted(counts.items()):
            print(f"{count:6d}  {verdict}")
        failed = [o for o in self.outcomes if o.verdict not in PASSING]
        print()
        if failed:
            print(
                f"FAIL: {len(failed)} of {len(self.outcomes)} comparisons are not equivalent."
            )
            return 1
        print(
            f"PASS: all {len(self.outcomes)} comparisons are equivalent or accepted."
        )
        return 0


@dataclasses.dataclass(frozen=True)
class ExtractedModule:
    """One build system's debs for one module, extracted and indexed.

    All of a module's debs land in a single tree, so the runtime deb and the -dbg deb merge
    and we can query a binary's debug information via build-id.
    """

    elfs: dict[str, Path]

    @staticmethod
    def _is_elf(path: Path) -> bool:
        """True if `path` starts with the ELF magic.

        Cheaper than running `file`.
        """
        with path.open("rb") as handle:
            return handle.read(4) == b"\x7fELF"

    @classmethod
    def extract(cls, debs: list[Path], root: Path, dpkg_deb: Tool) -> "ExtractedModule":
        root.mkdir(parents=True, exist_ok=True)
        for deb in debs:
            dpkg_deb.run("-x", str(deb), str(root))

        # Symlinks are skipped so a versioned .so and its aliases are only compared once.
        elfs = {
            "/" + str(path.relative_to(root)): path
            for path in sorted(root.rglob("*"))
            if path.is_file() and not path.is_symlink() and cls._is_elf(path)
        }
        return cls(elfs)

    @property
    def runtime(self) -> dict[str, Path]:
        """The shipped binaries, keyed by install path."""
        return {
            path: elf
            for path, elf in self.elfs.items()
            if not path.startswith(DEBUG_PREFIX)
        }

    @property
    def _debug_by_build_id(self) -> dict[str, Path]:
        """The .debug files, keyed by the build-id their filename encodes."""
        return {
            path[len(DEBUG_PREFIX) :].removesuffix(".debug").replace("/", ""): elf
            for path, elf in self.elfs.items()
            if path.startswith(DEBUG_PREFIX)
        }

    @staticmethod
    def _build_id(elf: Path, readelf: Tool) -> str | None:
        """The GNU build-id of `elf`, or None if it has none."""
        match = BUILD_ID_RE.search(readelf.run("-n", str(elf)).stdout)
        return match.group(1) if match else None

    def debug_info_for(self, binary: Path, tools: Tools) -> Path | None:
        """The .debug file holding `binary`'s symbols, or None if there is none."""
        identity = self._build_id(binary, tools.readelf)
        return self._debug_by_build_id.get(identity) if identity else None


def extract_module(
    module: str,
    pairs: list[DebPair],
    tools: Tools,
    reporter: Reporter,
    workdir: Path,
) -> tuple[ExtractedModule, ExtractedModule] | tuple[None, None]:
    """Extract both build systems' debs for `module`, as (make, bazel).

    (None, None) when a Make deb is missing.
    """
    missing = [pair for pair in pairs if not pair.make.exists()]
    for pair in missing:
        reporter.record(pair.label, Verdict.NO_MAKE_DEB, pair.make.name)
    if missing:
        return None, None

    return (
        ExtractedModule.extract(
            [pair.make for pair in pairs],
            workdir / module / "make",
            tools.dpkg_deb,
        ),
        ExtractedModule.extract(
            [pair.bazel for pair in pairs],
            workdir / module / "bazel",
            tools.dpkg_deb,
        ),
    )


def _record_verdict(
    artifact: rules.Artifact,
    verdict: Verdict,
    detail: str,
    reporter: Reporter,
) -> None:
    """Record a verdict, downgrading it if a rule accepts it."""
    for rule in rules.RULES:
        if isinstance(rule, rules.VerdictRule) and rule.matches(artifact, verdict):
            reporter.credit(rule.id)
            downgraded = (
                Verdict.ACCEPTED_BUT_INCOMPLETE
                if verdict in COVERAGE_GAPS
                else Verdict.ACCEPTED
            )
            reporter.record(artifact, downgraded, f"{verdict}: {rule.reason}")
            return
    reporter.record(artifact, verdict, detail)


def compare_module(
    module: str,
    make: ExtractedModule,
    bazel: ExtractedModule,
    tools: Tools,
    reporter: Reporter,
) -> None:
    """Compare every ELF a Bazel module ships, across all of its debs."""
    make_runtime, bazel_runtime = make.runtime, bazel.runtime
    make_only = make_runtime.keys() - bazel_runtime.keys()
    bazel_only = bazel_runtime.keys() - make_runtime.keys()
    for verdict, only, detail in (
        (Verdict.MAKE_ONLY, make_only, "Bazel ships no such binary"),
        (Verdict.BAZEL_ONLY, bazel_only, "Make ships no such binary"),
    ):
        for install_path in sorted(only):
            _record_verdict(
                rules.Artifact(module, install_path), verdict, detail, reporter
            )

    for install_path in sorted(make_runtime.keys() & bazel_runtime.keys()):
        left, right = make_runtime[install_path], bazel_runtime[install_path]
        _compare_one(rules.Artifact(module, install_path), left, right, tools, reporter)
        _compare_debug(module, install_path, left, right, make, bazel, tools, reporter)


def _partition_findings(
    artifact: rules.Artifact, findings: list[dict], reporter: Reporter
) -> list[dict]:
    """Return the findings no rule accepts, annotating and crediting the rest.

    An accepted finding stays in the report with `accepted_by` naming the rule,
    so what a rule swallowed is recoverable afterwards.
    """
    residue = []
    for finding in findings:
        for rule in rules.RULES:
            if isinstance(rule, rules.FindingRule) and rule.matches(artifact, finding):
                finding["accepted_by"] = rule.id
                reporter.credit(rule.id)
                break
        else:
            residue.append(finding)
    return residue


def _histogram(findings: list[dict]) -> str:
    """Condense findings into a per-category count, e.g. "10 function-removed, 1 elf"."""
    counts = collections.Counter(finding.get("category", "?") for finding in findings)
    return ", ".join(f"{count} {category}" for category, count in counts.most_common())


def _compare_one(
    artifact: rules.Artifact,
    left: Path,
    right: Path,
    tools: Tools,
    reporter: Reporter,
) -> None:
    """Compare one ELF pair, refusing to report a verdict on asymmetric input."""
    if has_symtab(left, tools.readelf) != has_symtab(right, tools.readelf):
        _record_verdict(
            artifact,
            Verdict.ASYMMETRIC,
            "only one side retains .symtab, so the function inventory cannot be compared. This is likely because of flag discrepancies when stripping binaries.",
            reporter,
        )
        return

    result = tools.elfcompare.run(
        str(left),
        str(right),
        check=False,
        env={
            "ELFCOMPARE_READELF": tools.readelf.command_line,
            "ELFCOMPARE_ABIDIFF": tools.abidiff.command_line,
        },
    )
    status = result.returncode
    verdict, detail = ELFCOMPARE_VERDICTS.get(
        status, (Verdict.ERROR, f"unexpected elfcompare exit status {status}")
    )
    if verdict is not Verdict.DIFFERENT:
        _record_verdict(artifact, verdict, detail, reporter)
        return

    try:
        findings = json.loads(result.stdout).get("findings", [])
    except json.JSONDecodeError:
        reporter.record(artifact, Verdict.ERROR, "elfcompare produced unreadable JSON")
        return

    if not findings:
        reporter.record(
            artifact,
            Verdict.ERROR,
            "elfcompare reported a difference with no findings",
        )
        return

    residue = _partition_findings(artifact, findings, reporter)
    if residue:
        reporter.record(artifact, Verdict.DIFFERENT, _histogram(residue), findings)
    else:
        # The binaries differ, and every difference is accounted for.
        reporter.record(
            artifact,
            Verdict.ACCEPTED,
            f"all accepted: {_histogram(findings)}",
            findings,
        )


def _compare_debug(
    module: str,
    install_path: str,
    left: Path,
    right: Path,
    make: ExtractedModule,
    bazel: ExtractedModule,
    tools: Tools,
    reporter: Reporter,
) -> None:
    """Compare the .debug files belonging to one runtime binary, if both exist.

    Useful to compare the list of declared functions in `.text`.
    """
    left_debug = make.debug_info_for(left, tools)
    right_debug = bazel.debug_info_for(right, tools)
    artifact = rules.Artifact(module, install_path, rules.Kind.DEBUG)

    if left_debug is None and right_debug is None:
        return
    if left_debug is None or right_debug is None:
        missing = "Make" if left_debug is None else "Bazel"
        _record_verdict(
            artifact,
            Verdict.NO_DEBUG,
            f"{missing} ships no .debug file",
            reporter,
        )
        return

    _compare_one(artifact, left_debug, right_debug, tools, reporter)


def collect_pairs(
    bldenv: str,
    build: bool,
) -> dict[str, list[DebPair]]:
    """Enumerate every comparable deb, grouped by module."""
    debs_path = registry_lib.REPO_ROOT / "target/debs" / bldenv
    repo_names = root_repo_names()
    by_module: dict[str, list[DebPair]] = {}

    for module, src_path in registry_lib.discover_top_level_bazel_modules():
        compared, excluded = query_deb_targets(registry_lib.REPO_ROOT / src_path)

        for label in excluded:
            print(f"[{module}] skip (tagged {EXCLUDE_TAG}): {label}", file=sys.stderr)

        if not compared:
            continue

        if module not in repo_names:
            print(
                f"[{module}] UNREACHABLE: not a bazel_dep of the root MODULE.bazel",
                file=sys.stderr,
            )
            continue

        by_module[module] = []
        for label in compared:
            label = f"@{repo_names[module]}{label}"
            bazel_deb = bazel_output_file(label, build=build)
            by_module[module].append(
                DebPair(label, debs_path / bazel_deb.name, bazel_deb)
            )

    return by_module


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bldenv",
        default="trixie",
        help="Debian release whose Make debs to compare against (slave.mk DEBS_PATH).",
    )
    parser.add_argument(
        "--print-make-debs",
        action="store_true",
        help="Print the Make debs this comparison needs, one relative path per line, and exit.",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Assume the Bazel debs are already built (they are still located with cquery).",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("target/elf-equivalence-report.json"),
        help="Where to write the run report, relative to the repo root.",
    )
    args = parser.parse_args()

    # Naming the debs only needs analysis, not execution.
    build = not (args.skip_build or args.print_make_debs)
    by_module = collect_pairs(args.bldenv, build=build)
    if not by_module:
        print("No comparable debs found.")
        return 1

    if args.print_make_debs:
        for pairs in by_module.values():
            for pair in pairs:
                print(pair.make.relative_to(registry_lib.REPO_ROOT))
        return 0

    tools = Tools.resolve()

    reporter = Reporter()
    with tempfile.TemporaryDirectory(prefix="elf-equivalence-") as tmp:
        for module, pairs in by_module.items():
            print(f"=== {module} ===")
            make, bazel = extract_module(module, pairs, tools, reporter, Path(tmp))
            if make is None or bazel is None:
                continue
            compare_module(module, make, bazel, tools, reporter)

    report = registry_lib.REPO_ROOT / args.report
    reporter.write_report(report)
    status = reporter.summarise()
    print(f"\nReport: {report.relative_to(registry_lib.REPO_ROOT)}")
    return status


if __name__ == "__main__":
    sys.exit(main())
