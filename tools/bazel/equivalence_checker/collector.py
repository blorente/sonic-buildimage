import progress
import registry_lib
from context import Context
from diagnostics import (
    ArtifactIdentifier,
    ArtifactType,
    CollectionDiagnosticCodeEnum,
    ComparableArtifact,
    Modifier,
)
from tools import BazelLabel

# Make writes debs under target/debs/<bldenv>/, and container archives straight into target/.
MAKE_DEBS_DIR = "target/debs"
MAKE_IMAGE_DIR = "target"

# slave.mk's DBG_IMAGE_MARK. Both build systems spell the debug variant this way.
DEBUG_MARK = "-dbg"


def _modifiers_for(name: str) -> frozenset[Modifier]:
    """Whether `name` is the debug variant of an artifact, or the shipped one."""
    return frozenset({Modifier.DEBUG if DEBUG_MARK in name else Modifier.RUNTIME})


def _bazel_label_identifier(
    label: BazelLabel,
    module: str | None = None
) -> ArtifactIdentifier:
    """The identity of the artifact `label` produces, including a module if adequate"""
    return ArtifactIdentifier(
        name=f"@{module}{label}" if module else label,
        source=None,
        modifiers=_modifiers_for(label),
    )


def _collect_debs(ctx: Context) -> list[ComparableArtifact]:
    """Every deb a top-level Bazel module declares, paired with its Make counterpart.

    Debs pair by filename: `sonic_deb` emits `<package>_<version>_<arch>.deb`, which is
    the Debian convention Make already follows.
    """
    make_dir = registry_lib.REPO_ROOT / MAKE_DEBS_DIR / ctx.debian_release
    repo_names = ctx.bazel.root_repo_names()
    artifacts = []

    for module, src_path in registry_lib.discover_top_level_bazel_modules():
        progress.start(f"LISTING DEBS IN {module}")
        compared, excluded = ctx.bazel.deb_targets(registry_lib.REPO_ROOT / src_path)
        progress.finish()

        skipped = set(excluded)

        for label in excluded + compared:
            identifier = _bazel_label_identifier(label, module)

            if label in skipped:
                ctx.sink.skip(
                    identifier,
                    CollectionDiagnosticCodeEnum.EXCLUDED_BY_TAG,
                    f"tagged {ctx.bazel.EXCLUDE_TAG}",
                )
                continue

            # A module the root workspace cannot see has no buildable label, so none
            # of its debs can be located.
            if module not in repo_names:
                ctx.sink.skip(
                    identifier,
                    CollectionDiagnosticCodeEnum.MODULE_UNREACHABLE,
                    f"{module} is not a bazel_dep of the root MODULE.bazel",
                )
                continue

            built = ctx.bazel.output_file(
                f"@{repo_names[module]}{label}", build=ctx.needs_build
            )
            artifact = ComparableArtifact(
                identifier=identifier,
                bazelVersion=built,
                makeVersion=make_dir / built.name,
                type=ArtifactType.DEB,
            )
            ctx.index.add(artifact)
            artifacts.append(artifact)

    return artifacts


def _collect_images(ctx: Context) -> list[ComparableArtifact]:
    """Every oci image the root module declares, paired by name with its Make equivalent."""
    make_dir = registry_lib.REPO_ROOT / MAKE_IMAGE_DIR
    progress.start("LISTING OCI IMAGES")
    compared, excluded = ctx.bazel.image_targets()
    progress.finish()
    skipped = set(excluded)
    artifacts = []

    for label in excluded + compared:
        identifier = _bazel_label_identifier(label)

        if label in skipped:
            ctx.sink.skip(
                identifier,
                CollectionDiagnosticCodeEnum.EXCLUDED_BY_TAG,
                f"tagged {ctx.bazel.EXCLUDE_TAG}",
            )
            continue

        # Images live in the root module, so the label is already buildable as it stands.
        built = ctx.bazel.output_file(label, build=ctx.needs_build)
        artifact = ComparableArtifact(
            identifier=identifier,
            bazelVersion=built,
            makeVersion=make_dir / built.name,
            type=ArtifactType.OCI_IMAGE,
        )
        ctx.index.add(artifact)
        artifacts.append(artifact)

    return artifacts


def collect_artifacts(ctx: Context) -> list[ComparableArtifact]:
    """Run Bazel queries to find out which top-level artifacts we need to compare (debs and OCI images).

    Collects diagnostics in the diagnostics sink, and returns a merged list of artifacts,
    containing deb packages and oci images.
    """
    return _collect_debs(ctx) + _collect_images(ctx)
