from dataclasses import dataclass, field
import enum
from pathlib import Path
from typing import TypeAlias

import registry_lib


ArtifactName: TypeAlias = str

class ArtifactType(enum.StrEnum):
    DEB = "DEB"
    OCI_IMAGE = "OCI_IMAGE"
    ELF_EXECUTABLE = "ELF_EXECUTABLE"
    # The .debug file carrying a binary's symbols.
    # They are ELFs themselves, but it's a useful differentiation for reporting.
    ELF_DEBUG_INFO = "ELF_DEBUG_INFO"
    FILE = "FILE"
    DIRECTORY = "DIRECTORY"
    LINK = "LINK"

class Modifier(enum.StrEnum):
    """Distinguishers for artifacts that share a name."""

    # The binary as shipped.
    RUNTIME = "runtime"
    # The debug information belonging to that binary.
    DEBUG = "debug"


@dataclass(frozen=True)
class ArtifactIdentifier:
    name: ArtifactName
    source: "ArtifactIdentifier | None"
    modifiers: frozenset[Modifier]

    def __str__(self) -> str:
        text = self.name
        if self.modifiers:
            text += f" ({', '.join(sorted(self.modifiers))})"
        if self.source is not None:
            text += f" in {self.source}"
        return text


@dataclass()
class ComparableArtifact():
    identifier: ArtifactIdentifier
    bazelVersion: Path
    makeVersion: Path
    type: ArtifactType

    @staticmethod
    def _relative(path: Path) -> str:
        """`path` against the repo root, or as it stands when it lies outside."""
        try:
            return str(path.relative_to(registry_lib.REPO_ROOT))
        except ValueError:
            return str(path)

    @property
    def printable(self) -> str:
        """This artifact and both of its paths, as three lines for a terminal."""
        return f"""{self.type} {self.identifier}
    bazel: {self._relative(self.bazelVersion)}
    make:  {self._relative(self.makeVersion)}"""


@dataclass(frozen=True)
class ArtifactIndex:
    """Every artifact to compare, keyed by identity.

    Insertion fails if element is already there, so an identifier names exactly one artifact.
    """

    artifacts: dict[ArtifactIdentifier, ComparableArtifact] = field(default_factory=dict)

    def add(self, artifact: ComparableArtifact) -> None:
        existing = self.artifacts.get(artifact.identifier)
        if existing is not None:
            raise ValueError(
                f"{artifact.identifier} already names {existing.bazelVersion}, "
                f"so it cannot also name {artifact.bazelVersion}"
            )
        self.artifacts[artifact.identifier] = artifact

    def __getitem__(self, identifier: ArtifactIdentifier) -> ComparableArtifact:
        return self.artifacts[identifier]

    def __len__(self) -> int:
        return len(self.artifacts)


class ElfDiagnosticCodeEnum(enum.StrEnum):
    """Diagnostics detected when comparing two ELFs. One comparison may generate more than one diagnostic."""

    # Public findings from compareELF
    ABI = "abi"
    DEPENDENCY = "dependency"
    ELF = "elf"
    EXPORT_ADDED = "export-added"
    EXPORT_CHANGED = "export-changed"
    EXPORT_REMOVED = "export-removed"
    FUNCTION_ADDED = "function-added"
    FUNCTION_REMOVED = "function-removed"
    IMPORT_ADDED = "import-added"
    IMPORT_CHANGED = "import-changed"
    IMPORT_REMOVED = "import-removed"
    RUNTIME = "runtime"
    RUNTIME_VERSION = "runtime-version"
    SECURITY = "security"
    STARTUP_CALLBACK = "startup-callback"

    # Outcomes of a whole comparison.
    # Only one side kept .symtab, so the function inventory cannot be compared.
    DIFFERENT_STRIP_LEVELS = "DIFFERENT_STRIP_LEVELS"
    # Part of elfcompare's analysis did not run.
    INCOMPLETE = "INCOMPLETE"
    # A side could not be read as an ELF.
    UNPARSEABLE = "UNPARSEABLE"
    # elfcompare itself failed, or reported a difference it could not describe.
    ERROR = "ERROR"

@dataclass(frozen=True)
class ElfDiagnosticCode:
    code: ElfDiagnosticCodeEnum


class CollectionDiagnosticCodeEnum(enum.StrEnum):
    """Things that go wrong while working out what there is to compare."""

    EXCLUDED_BY_TAG = "EXCLUDED_BY_TAG"
    MODULE_UNREACHABLE = "MODULE_UNREACHABLE"
    NO_MAKE_ARTIFACT = "NO_MAKE_ARTIFACT"
    NO_BAZEL_ARTIFACT = "NO_BAZEL_ARTIFACT"

@dataclass(frozen=True)
class CollectionDiagnosticCode:
    code: CollectionDiagnosticCodeEnum


class ExtractionDiagnosticCodeEnum(enum.StrEnum):
    """Things that go wrong while unpacking an artifact to find what is inside it."""

    MAKE_ONLY = "MAKE_ONLY"
    BAZEL_ONLY = "BAZEL_ONLY"
    # The file is unreadable (mode-000).
    UNREADABLE = "UNREADABLE"
    # Both sides ship the binary, but only one side ships debug information.
    NO_DEBUG = "NO_DEBUG"

@dataclass(frozen=True)
class ExtractionDiagnosticCode:
    code: ExtractionDiagnosticCodeEnum


class FileDiagnosticCodeEnum(enum.StrEnum):
    """How a pair that is not an ELF came out."""

    # Two files which do not hold the same bytes.
    CONTENT_MISMATCH = "CONTENT_MISMATCH"
    # Two symlinks with the same name, but pointing to different places.
    TARGET_MISMATCH = "TARGET_MISMATCH"

@dataclass(frozen=True)
class FileDiagnosticCode:
    code: FileDiagnosticCodeEnum

DiagnosticCode: TypeAlias = (
    ElfDiagnosticCode
    | CollectionDiagnosticCode
    | ExtractionDiagnosticCode
    | FileDiagnosticCode
)

# Each family, with the wrapper that puts one of its codes into the union.
_CODE_FAMILIES = (
    (ElfDiagnosticCodeEnum, ElfDiagnosticCode),
    (CollectionDiagnosticCodeEnum, CollectionDiagnosticCode),
    (ExtractionDiagnosticCodeEnum, ExtractionDiagnosticCode),
    (FileDiagnosticCodeEnum, FileDiagnosticCode),
)


def _every_code() -> dict[str, DiagnosticCode]:
    """Every code from every family, by name.

    Two families using one name would shadow each other silently, so that is an
    error rather than a surprise later.
    """
    flat: dict[str, DiagnosticCode] = {}
    for family, wrap in _CODE_FAMILIES:
        for member in family:
            if member.name in flat:
                raise ValueError(
                    f"{member.name} is defined by two diagnostic families"
                )
            flat[member.name] = wrap(member)
    return flat


# Every code under one name.
# This way, a rule can say `Codes.MAKE_ONLY` without knowing which family it came from.
# We want the internal structure of enums for destructuring, but we want to make writing rules easy.
Codes = enum.Enum("Codes", _every_code(), module=__name__)


@dataclass(frozen=True)
class Diagnostic:
    artifact: ArtifactIdentifier
    code: DiagnosticCode
    msg: str


@dataclass(frozen=True)
class DiagnosticSink:
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def record(self, diagnostic: Diagnostic) -> None:
        self.diagnostics.append(diagnostic)

    def skip(
        self,
        artifact: ArtifactIdentifier,
        code: CollectionDiagnosticCodeEnum,
        msg: str,
    ) -> None:
        """Note something that kept `artifact` out of the comparison."""
        assert isinstance(code, CollectionDiagnosticCodeEnum), (
            f"skip() takes a collection code, not {code!r}"
        )
        self.record(Diagnostic(artifact, CollectionDiagnosticCode(code), msg))

    def unpaired(
        self,
        artifact: ArtifactIdentifier,
        code: ExtractionDiagnosticCodeEnum,
        msg: str,
    ) -> None:
        """Note something found while unpacking that has nothing to compare against."""
        assert isinstance(code, ExtractionDiagnosticCodeEnum), (
            f"unpaired() takes an extraction code, not {code!r}"
        )
        self.record(Diagnostic(artifact, ExtractionDiagnosticCode(code), msg))

    def elf_mismatch(
        self,
        artifact: ArtifactIdentifier,
        code: ElfDiagnosticCodeEnum,
        msg: str,
    ) -> None:
        """Note one way in which the two sides of an ELF pair disagree."""
        assert isinstance(code, ElfDiagnosticCodeEnum), (
            f"elf_mismatch() takes an ELF code, not {code!r}"
        )
        self.record(Diagnostic(artifact, ElfDiagnosticCode(code), msg))

    def file_mismatch(
        self,
        artifact: ArtifactIdentifier,
        code: FileDiagnosticCodeEnum,
        msg: str,
    ) -> None:
        """Note that the two sides of a non-ELF pair disagree."""
        assert isinstance(code, FileDiagnosticCodeEnum), (
            f"file_mismatch() takes a file code, not {code!r}"
        )
        self.record(Diagnostic(artifact, FileDiagnosticCode(code), msg))

