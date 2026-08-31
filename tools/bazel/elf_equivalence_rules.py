"""Differences between the Make and Bazel builds that are accepted as expected.

Each rule names a difference the two builds produce on purpose.

Rules come in two shapes, and the type says which is allowed where:

  * FindingRule accepts a category of elfcompare findings on one artifact.
    This is how a DIFFERENT artifact is accepted 
  * VerdictRule accepts a whole verdict, and only verdicts that carry no findings.
    As a consequence, we don't accept a DIFFERENT verdict.
    We need to accept all the individual findings.
"""

import collections
import dataclasses
import enum
import fnmatch
from collections.abc import Iterator
from typing import Any


class Kind(enum.StrEnum):
    """Whether the package came from the (stripped) runtime binary or its debug information."""

    RUNTIME = "runtime"
    DEBUG = "debug"


@dataclasses.dataclass(frozen=True)
class Artifact:
    """One ELF, identified the same way on both sides of a comparison.

    `path` is the install path, which is what the two build systems agree on.
    `kind` separates a stripped binary from the .debug file holding its symbols.
    """

    module: str
    path: str
    kind: Kind = Kind.RUNTIME

    def __str__(self) -> str:
        """The identity, in full.

        Two modules can install the same path, so the module is part of what
        names an artifact and not just a heading above it.
        """
        return f"{self.module}:{self.path}:{self.kind}"


class DowngradableVerdict(enum.StrEnum):
    """The verdicts a VerdictRule may name.

    DIFFERENT is absent because it always has findings, which we must accept individually.
    UNPARSEABLE, ERROR and NO-MAKE-DEB are absent because they report tool failures, and thus are always bad.
    """

    MAKE_ONLY = "MAKE-ONLY"
    BAZEL_ONLY = "BAZEL-ONLY"
    INCOMPLETE = "INCOMPLETE"
    ASYMMETRIC = "ASYMMETRIC"
    NO_DEBUG = "NO-DEBUG"


@dataclasses.dataclass(frozen=True)
class FindingRule:
    """Accepts one category of findings on one artifact.

    `name` is an fnmatch pattern over the finding's name, defaulting to every
    name in the category. A category-wide rule accepts that category on that
    artifact for good, including findings that appear later, so narrow it with
    `name` wherever the evidence allows.
    """

    # TODO(bazel-ready): add an optional expected count, so a rule that starts
    # matching more findings than it expected fails.
    id: str
    artifact: Artifact
    category: str
    reason: str
    name: str = "*"
    comment: str = ""

    def matches(self, artifact: Artifact, finding: dict[str, Any]) -> bool:
        return (
            artifact == self.artifact
            and finding.get("category") == self.category
            and fnmatch.fnmatchcase(str(finding.get("name", "")), self.name)
        )


@dataclasses.dataclass(frozen=True)
class VerdictRule:
    """Accepts a whole verdict on one artifact."""

    id: str
    artifact: Artifact
    verdict: DowngradableVerdict
    reason: str
    comment: str = ""

    def matches(self, artifact: Artifact, verdict: str) -> bool:
        return artifact == self.artifact and verdict == self.verdict


class Rules:
    """Every accepted difference.

    We wrap it in a class to perform collection-wide checks at initialization.
    """

    def __init__(self, *rules: FindingRule | VerdictRule) -> None:
        duplicates = sorted(
            rule_id
            for rule_id, count in collections.Counter(r.id for r in rules).items()
            if count > 1
        )
        if duplicates:
            raise ValueError(f"duplicate rule ids: {', '.join(duplicates)}")

        self._rules = rules

    def __iter__(self) -> Iterator[FindingRule | VerdictRule]:
        return iter(self._rules)


# Artifacts

SYSMGR = "sonic-sysmgr"

REBOOTBACKEND = Artifact(SYSMGR, "/usr/bin/rebootbackend")
REBOOTBACKEND_DEBUG = Artifact(SYSMGR, "/usr/bin/rebootbackend", Kind.DEBUG)
LIBREBOOTGNOI = Artifact(SYSMGR, "/usr/lib/x86_64-linux-gnu/librebootgnoi.so.0.0.0")


# Rules

RULES = Rules(
    VerdictRule(
        id="sysmgr-librebootgnoi-not-shipped",
        artifact=LIBREBOOTGNOI,
        verdict=DowngradableVerdict.MAKE_ONLY,
        reason=(
            "In Bazel, rebootbackend links statically against the C++ stdlib and gnoi"
        ),
    ),
    FindingRule(
        id="sysmgr-rebootbackend-static-imports-cpp-stdlib",
        artifact=REBOOTBACKEND,
        category="import-added",
        reason=(
            "In Bazel, rebootbackend links statically against the C++ stdlib and gnoi"
            "Therefore, it's going to import more symbols."
        ),
        name="*@GLIBCXX_*",
        comment=(
            "Scoped to the C++ stdlib just to test the rules engine"
        ),
    ),
    FindingRule(
        id="sysmgr-rebootbackend-static-imports-all",
        artifact=REBOOTBACKEND,
        category="import-added",
        reason=(
            "In Bazel, rebootbackend links statically against the C++ stdlib and gnoi"
            "Therefore, it's going to import more symbols."
        ),
    ),
)
