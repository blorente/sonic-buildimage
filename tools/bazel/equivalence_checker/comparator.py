"""Compares the two sides of every paired artifact, recording what differs."""

import dataclasses
import filecmp
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import progress
from context import Context
from diagnostics import (
    ArtifactType,
    ComparableArtifact,
    DiagnosticSink,
    ElfDiagnosticCodeEnum,
    FileDiagnosticCodeEnum,
)
from tools import Tool


# elfcompare's exit statuses.
EXIT_CLEAN = 0
EXIT_DIFFERENT = 1
EXIT_UNPARSEABLE = 2
EXIT_INCOMPLETE = 3

# An exit status that says nothing more than itself maps straight onto a code.
ELFCOMPARE_STATUS_CODES = {
    EXIT_UNPARSEABLE: (
        ElfDiagnosticCodeEnum.UNPARSEABLE,
        "elfcompare could not read an artifact",
    ),
    EXIT_INCOMPLETE: (
        ElfDiagnosticCodeEnum.INCOMPLETE,
        "part of the analysis did not run",
    ),
}


def _has_symtab(elf: Path, readelf: Tool) -> bool:
    """True if `elf` still carries .symtab.

    Useful to detect drift in stripping options.
    """
    return " .symtab" in readelf.run("-S", str(elf)).stdout


def _code_of(finding: dict) -> ElfDiagnosticCodeEnum:
    """The code for one finding's category.

    The enum spells elfcompare's public categories exactly.
    """
    try:
        return ElfDiagnosticCodeEnum(finding.get("category"))
    except ValueError:
        return ElfDiagnosticCodeEnum.ERROR


def _compare_elf(ctx: Context, artifact: ComparableArtifact) -> None:
    """Compare one ELF pair with elfcompare.

    Every finding elfcompare reports becomes its own diagnostic, because one pair
    can disagree in several unrelated ways at once.
    """
    tools = ctx.tools
    identifier = artifact.identifier

    # If the files are identical, just move on.
    if filecmp.cmp(artifact.makeVersion, artifact.bazelVersion, shallow=False):
        return

    # With .symtab on one side only there is no function inventory to compare,
    # so elfcompare's answer would not mean anything.
    if _has_symtab(artifact.makeVersion, tools.readelf) != _has_symtab(
        artifact.bazelVersion, tools.readelf
    ):
        ctx.sink.elf_mismatch(
            identifier,
            ElfDiagnosticCodeEnum.DIFFERENT_STRIP_LEVELS,
            "only one side retains .symtab, which usually means the two builds strip "
            "with different flags",
        )
        return

    result = tools.elfcompare.run(
        str(artifact.makeVersion),
        str(artifact.bazelVersion),
        check=False,
        env={
            "ELFCOMPARE_READELF": tools.readelf.command_line,
            "ELFCOMPARE_ABIDIFF": tools.abidiff.command_line,
        },
    )

    if result.returncode == EXIT_CLEAN:
        return

    if result.returncode in ELFCOMPARE_STATUS_CODES:
        code, detail = ELFCOMPARE_STATUS_CODES[result.returncode]
        ctx.sink.elf_mismatch(identifier, code, detail)
        return

    if result.returncode != EXIT_DIFFERENT:
        ctx.sink.elf_mismatch(
            identifier,
            ElfDiagnosticCodeEnum.ERROR,
            f"unexpected elfcompare exit status {result.returncode}",
        )
        return

    try:
        findings = json.loads(result.stdout).get("findings", [])
    except json.JSONDecodeError:
        ctx.sink.elf_mismatch(
            identifier,
            ElfDiagnosticCodeEnum.ERROR,
            "elfcompare produced unreadable JSON",
        )
        return

    if not findings:
        ctx.sink.elf_mismatch(
            identifier,
            ElfDiagnosticCodeEnum.ERROR,
            "elfcompare reported a difference with no findings",
        )
        return

    for finding in findings:
        ctx.sink.elf_mismatch(identifier, _code_of(finding), json.dumps(finding))


def _compare_file(ctx: Context, artifact: ComparableArtifact) -> None:
    """Compare one non-ELF file pair byte for byte."""
    if filecmp.cmp(artifact.makeVersion, artifact.bazelVersion, shallow=False):
        return

    ctx.sink.file_mismatch(
        artifact.identifier,
        FileDiagnosticCodeEnum.CONTENT_MISMATCH,
        f"make is {artifact.makeVersion.stat().st_size} bytes, "
        f"bazel is {artifact.bazelVersion.stat().st_size}",
    )


def _compare_link(ctx: Context, artifact: ComparableArtifact) -> None:
    """Compare where two symlinks point.

    The target is read as it was written, not resolved.
    """
    make_target = artifact.makeVersion.readlink()
    bazel_target = artifact.bazelVersion.readlink()
    if make_target == bazel_target:
        return

    ctx.sink.file_mismatch(
        artifact.identifier,
        FileDiagnosticCodeEnum.TARGET_MISMATCH,
        f"make points at {make_target}, bazel points at {bazel_target}",
    )


def _compare_one(ctx: Context, artifact: ComparableArtifact) -> DiagnosticSink:
    """Compare one artifact, into a sink of its own."""
    own = dataclasses.replace(ctx, sink=DiagnosticSink())
    match artifact.type:
        case ArtifactType.ELF_EXECUTABLE | ArtifactType.ELF_DEBUG_INFO:
            _compare_elf(own, artifact)
        case ArtifactType.FILE:
            _compare_file(own, artifact)
        case ArtifactType.LINK:
            _compare_link(own, artifact)
        case _:
            raise ValueError(f"nothing knows how to compare a {artifact.type}")
    return own.sink


def compare_artifacts(ctx: Context, artifacts: list[ComparableArtifact]) -> None:
    """Compare every paired artifact, recording differences in the sink.

    An artifact the two build systems agree on records nothing.
    """
    with ThreadPoolExecutor(max_workers=ctx.jobs) as pool:
        sinks = pool.map(lambda artifact: _compare_one(ctx, artifact), artifacts)
        for artifact, sink in zip(artifacts, sinks):
            progress.step(f"COMPARED {artifact.identifier}")
            for diagnostic in sink.diagnostics:
                ctx.sink.record(diagnostic)
