"""Unpacks a top-level artifact (OCI image or deb archive) into the individual files worth comparing."""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import progress
from context import Context
from diagnostics import (
    ArtifactIdentifier,
    ArtifactType,
    CollectionDiagnosticCodeEnum,
    ComparableArtifact,
    ExtractionDiagnosticCodeEnum,
    Modifier,
)
from tools import Tool


def _is_elf(path: Path) -> bool:
    """True if `path` starts with the ELF magic.

    Cheaper than running `file`.
    """
    try:
        with path.open("rb") as handle:
            return handle.read(4) == b"\x7fELF"
    except OSError:
        # An unreadable file is not something we can compare either way.
        return False


# Debug files live at /usr/lib/debug/.build-id/NN/REST.debug.
DEBUG_PREFIX = "/usr/lib/debug/.build-id/"

# What is worth pairing between the two sides.
COMPARABLE_TYPES = (
    ArtifactType.ELF_EXECUTABLE,
    ArtifactType.FILE,
    ArtifactType.LINK,
)


BUILD_ID_RE = re.compile(r"Build ID:\s*([0-9a-f]+)")


def _build_id_of_debug_file(install_path: str) -> str:
    """The build-id a debug file's own path encodes.

    Debug files are content-addressed: /usr/lib/debug/.build-id/93/e50c...debug
    belongs to the binary whose build-id is 93e50c...
    """
    return install_path[len(DEBUG_PREFIX):].removesuffix(".debug").replace("/", "")


def _build_id_of_binary(path: Path, readelf: Tool) -> str | None:
    """The GNU build-id recorded in `path`, or None if it carries none."""
    match = BUILD_ID_RE.search(readelf.run("-n", str(path)).stdout)
    return match.group(1) if match else None


def _entry_identifier(
    install_path: str, source: ArtifactIdentifier
) -> ArtifactIdentifier:
    """The identity of one entry, as found inside `source`."""
    return ArtifactIdentifier(
        name=install_path,
        source=source,
        modifiers=frozenset({Modifier.RUNTIME}),
    )


def _type_of(path: Path) -> ArtifactType | None:
    """Which kind of artifact `path` is, or None if it is nothing we compare.

    Symlinks are tested first, because `is_dir` and `is_file` both follow them.
    """
    if path.is_symlink():
        return ArtifactType.LINK
    if path.is_dir():
        return ArtifactType.DIRECTORY
    if not path.is_file():
        # A device, fifo or socket has no contents to compare.
        return None
    return ArtifactType.ELF_EXECUTABLE if _is_elf(path) else ArtifactType.FILE


@dataclass(frozen=True)
class UnpackedTree:
    """What one side unpacked.
    
    For each ArtifactType, store a map of install path -> real path.
    """

    entries: dict[ArtifactType, dict[str, Path]] = field(
        default_factory=lambda: defaultdict(dict)
    )

    def of(self, kind: ArtifactType) -> dict[str, Path]:
        """The entries of one kind, keyed by install path."""
        return self.entries[kind]


@dataclass(frozen=True)
class DebugFiles:
    """Every .debug file each side ships, keyed by the build-id that owns it.

    Debug files are named after build-ids, which diverge from build to build.
    This mapping allows us to tie debug files back to the binaries they originate from.
    """

    make: dict[str, Path] = field(default_factory=dict)
    bazel: dict[str, Path] = field(default_factory=dict)


def _index_tree(root: Path) -> UnpackedTree:
    """Walk `root` once, bucketing every entry by what kind of artifact it is."""
    tree = UnpackedTree()
    for path in sorted(root.rglob("*")):
        kind = _type_of(path)
        if kind is not None:
            tree.entries[kind]["/" + str(path.relative_to(root))] = path
    return tree


def _harvest_debug(tree: UnpackedTree, into: dict[str, Path]) -> None:
    """Move `tree`'s debug files into the build-id index.

    Note that this modifies the UnpackedTree.
    """
    elfs = tree.of(ArtifactType.ELF_EXECUTABLE)
    for install_path in [p for p in elfs if p.startswith(DEBUG_PREFIX)]:
        into[_build_id_of_debug_file(install_path)] = elfs.pop(install_path)


def _pair(
    ctx: Context,
    source: ComparableArtifact,
    make: UnpackedTree,
    bazel: UnpackedTree,
    debug: DebugFiles,
) -> list[ComparableArtifact]:
    """Pair what the two sides unpacked, by kind and install path.

    Debug files are set aside for `pair_debug_info`, which pairs them by build-id rather than by path.
    If we can't find something to pair against, we report it and move on.
    """
    _harvest_debug(make, debug.make)
    _harvest_debug(bazel, debug.bazel)

    paired = []
    for kind in COMPARABLE_TYPES:
        make_entries, bazel_entries = make.of(kind), bazel.of(kind)

        for code, install_paths, detail in (
            (
                ExtractionDiagnosticCodeEnum.MAKE_ONLY,
                make_entries.keys() - bazel_entries.keys(),
                "Bazel ships no such entry",
            ),
            (
                ExtractionDiagnosticCodeEnum.BAZEL_ONLY,
                bazel_entries.keys() - make_entries.keys(),
                "Make ships no such entry",
            ),
        ):
            for install_path in sorted(install_paths):
                ctx.sink.unpaired(
                    _entry_identifier(install_path, source.identifier), code, detail
                )

        for install_path in sorted(make_entries.keys() & bazel_entries.keys()):
            extracted = ComparableArtifact(
                identifier=_entry_identifier(install_path, source.identifier),
                bazelVersion=bazel_entries[install_path],
                makeVersion=make_entries[install_path],
                type=kind,
            )
            ctx.index.add(extracted)
            paired.append(extracted)

    return paired


def _debug_for(binary: Path, side: dict[str, Path], readelf: Tool) -> Path | None:
    """The debug file holding `binary`'s symbols, or None if that side ships none."""
    build_id = _build_id_of_binary(binary, readelf)
    return side.get(build_id) if build_id else None


def pair_debug_info(
    ctx: Context, artifacts: list[ComparableArtifact], debug: DebugFiles
) -> list[ComparableArtifact]:
    """Pair the debug information belonging to each runtime binary, by build-id.

    The pair takes the name of the binary that owns it, because the debug files
    themselves are named after their own contents and so never agree across builds.
    """
    paired = []
    for artifact in artifacts:
        if artifact.type is not ArtifactType.ELF_EXECUTABLE:
            continue

        make_debug = _debug_for(artifact.makeVersion, debug.make, ctx.tools.readelf)
        bazel_debug = _debug_for(artifact.bazelVersion, debug.bazel, ctx.tools.readelf)
        if make_debug is None and bazel_debug is None:
            continue

        identifier = ArtifactIdentifier(
            name=artifact.identifier.name,
            source=artifact.identifier.source,
            modifiers=frozenset({Modifier.DEBUG}),
        )

        if make_debug is None or bazel_debug is None:
            missing = "Make" if make_debug is None else "Bazel"
            ctx.sink.unpaired(
                identifier,
                ExtractionDiagnosticCodeEnum.NO_DEBUG,
                f"{missing} ships no debug information for this binary",
            )
            continue

        extracted = ComparableArtifact(
            identifier=identifier,
            bazelVersion=bazel_debug,
            makeVersion=make_debug,
            type=ArtifactType.ELF_DEBUG_INFO,
        )
        ctx.index.add(extracted)
        paired.append(extracted)

    return paired


def _roots_for(ctx: Context, artifact: ComparableArtifact) -> tuple[Path, Path]:
    """Where each side of `artifact` should unpack its contents to, as (make, bazel)."""
    base = ctx.workdir / artifact.type / artifact.bazelVersion.name
    return base / "make", base / "bazel"


def _extract_deb(
    ctx: Context, artifact: ComparableArtifact, debug: DebugFiles
) -> list[ComparableArtifact]:
    """Unpack both sides of a deb and pair what is inside them."""
    make_root, bazel_root = _roots_for(ctx, artifact)
    for root, deb in (
        (make_root, artifact.makeVersion),
        (bazel_root, artifact.bazelVersion),
    ):
        root.mkdir(parents=True, exist_ok=True)
        ctx.tools.dpkg_deb.run("-x", str(deb), str(root))

    return _pair(
        ctx, artifact, _index_tree(make_root), _index_tree(bazel_root), debug
    )


def _extract_oci_image(
    ctx: Context, artifact: ComparableArtifact, debug: DebugFiles
) -> list[ComparableArtifact]:
    """Unpack both sides of a container archive and pair the ELFs inside them."""
    # TODO BL: impelement this later
    return []


def extract_all(
    ctx: Context, sources: list[ComparableArtifact]
) -> list[ComparableArtifact]:
    """Unpack every source artifact into the entries to compare inside them."""
    debug = DebugFiles()

    extracted = []
    for source in sources:
        progress.start(f"EXTRACTING {source.identifier}")
        extracted += extract_source(ctx, source, debug)
        progress.finish()

    # Collect the debug info in a second pass, because we need all the binaries in scope
    # to be able to tie them to their debug information.
    progress.start("MATCHING DEBUG INFORMATION")
    with_debug = extracted + pair_debug_info(ctx, extracted, debug)
    progress.finish()
    return with_debug


def extract_source(
    ctx: Context, artifact: ComparableArtifact, debug: DebugFiles
) -> list[ComparableArtifact]:
    """Unpack one top-level artifact into the files to compare inside it."""
    # Make builds on demand, so its side of a pair is missing until someone builds it.
    if not artifact.makeVersion.exists():
        ctx.sink.skip(
            artifact.identifier,
            CollectionDiagnosticCodeEnum.NO_MAKE_ARTIFACT,
            f"Make has not built {artifact.makeVersion}",
        )
        return []

    match artifact.type:
        case ArtifactType.DEB:
            return _extract_deb(ctx, artifact, debug)
        case ArtifactType.OCI_IMAGE:
            return _extract_oci_image(ctx, artifact, debug)
        case _:
            raise ValueError(f"nothing knows how to unpack a {artifact.type}")
