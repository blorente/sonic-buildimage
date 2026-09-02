from dataclasses import dataclass, field
import enum
from pathlib import Path
from typing import TypeAlias


ArtifactName: TypeAlias = str

class ArtifactType(enum.StrEnum):
    DEB = "DEB"
    OCI_IMAGE = "OCI_IMAGE"
    ELF_EXECUTABLE = "ELF_EXECUTABLE"
    FILE = "FILE"

@dataclass(frozen=True)
class ArtifactIdentifier:
    name: ArtifactName
    source: "ArtifactIdentifier | None"
    modifiers: frozenset[str] # E.g. 'debug' or 'runtime'

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
    INIT_MISMATCH = "INIT_MISMATCH"

@dataclass(frozen=True)
class ElfDiagnosticCode:
    code: ElfDiagnosticCodeEnum


class CollectionDiagnosticCodeEnum(enum.StrEnum):
    """Things that go wrong while working out what there is to compare."""

    EXCLUDED_BY_TAG = "EXCLUDED_BY_TAG"
    MODULE_UNREACHABLE = "MODULE_UNREACHABLE"
    NO_MAKE_ARTIFACT = "NO_MAKE_ARTIFACT"

@dataclass(frozen=True)
class CollectionDiagnosticCode:
    code: CollectionDiagnosticCodeEnum

DiagnosticCode: TypeAlias = ElfDiagnosticCode | CollectionDiagnosticCode


@dataclass(frozen=True)
class Diagnostic:
    artifact: ArtifactIdentifier
    code: DiagnosticCode
    msg: str


@dataclass(frozen=True)
class AcceptanceRule:
    sourceMather: list[str]
    codeMatcher: DiagnosticCode
    reason: str



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

