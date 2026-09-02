"""Differences between the Make and Bazel builds that are accepted as expected.

Each rule names a difference the two builds produce on purpose, and says why.
A rule matches a diagnostic on its code plus where the artifact came from, so
one rule can cover a whole install path or a whole source package.
"""

import collections
import fnmatch
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TypeAlias

from diagnostics import (
    Diagnostic,
    DiagnosticCode,
    ElfDiagnosticCode,
    ElfDiagnosticCodeEnum,
    ExtractionDiagnosticCode,
    ExtractionDiagnosticCodeEnum,
)


@dataclass(frozen=True)
class AnyCode:
    """Matches every code, whichever family it belongs to."""


ANY_CODE = AnyCode()

CodeMatcher: TypeAlias = DiagnosticCode | AnyCode


@dataclass(frozen=True)
class DiagnosticMatcher:
    """Which diagnostics something applies to.

    `nameMatcher` and `sourceMatcher` are fnmatch patterns over a ComparableArtifact's name and source.
    `msgMatcher` is also an fnmatch pattern, over the diagnostic's own message.
    """

    codeMatcher: CodeMatcher
    nameMatcher: str
    sourceMatcher: str
    msgMatcher: str = "*"

    def matches(self, diagnostic: Diagnostic) -> bool:
        artifact = diagnostic.artifact
        source = artifact.source.name if artifact.source is not None else ""
        return (
            self._code_matches(diagnostic.code)
            and fnmatch.fnmatchcase(artifact.name, self.nameMatcher)
            and fnmatch.fnmatchcase(source, self.sourceMatcher)
            and fnmatch.fnmatchcase(diagnostic.msg, self.msgMatcher)
        )

    def _code_matches(self, code: DiagnosticCode) -> bool:
        if isinstance(self.codeMatcher, AnyCode):
            return True
        return code == self.codeMatcher


@dataclass(frozen=True)
class AcceptanceRule:
    """A difference in produced artifacts that we're ready to accept."""

    id: str
    matcher: DiagnosticMatcher
    reason: str
    comment: str = ""

    def matches(self, diagnostic: Diagnostic) -> bool:
        return self.matcher.matches(diagnostic)


class Rules:
    """Every accepted difference.

    Wrapped in a class so the whole collection can be checked as it is built.
    """

    def __init__(self, *rules: AcceptanceRule) -> None:
        duplicates = sorted(
            rule_id
            for rule_id, count in collections.Counter(r.id for r in rules).items()
            if count > 1
        )
        if duplicates:
            raise ValueError(f"duplicate rule ids: {', '.join(duplicates)}")

        self._rules = rules

    def __iter__(self) -> Iterator[AcceptanceRule]:
        return iter(self._rules)

    def accepting(self, diagnostic: Diagnostic) -> AcceptanceRule | None:
        """The first rule that accepts `diagnostic`, or None if none does."""
        return next((rule for rule in self._rules if rule.matches(diagnostic)), None)


Classified: TypeAlias = list[tuple[Diagnostic, AcceptanceRule | None]]


def classify(diagnostics: list[Diagnostic], rules: "Rules") -> Classified:
    """Pair every diagnostic with the rule that accepts it, or None if none does."""
    return [(diagnostic, rules.accepting(diagnostic)) for diagnostic in diagnostics]


SYSMGR_DEB = "@sonic-sysmgr//:sysmgr_deb"

RULES = Rules(
    AcceptanceRule(
        id="sysmgr-librebootgnoi-not-shipped",
        matcher=DiagnosticMatcher(
            codeMatcher=ExtractionDiagnosticCode(
                ExtractionDiagnosticCodeEnum.MAKE_ONLY
            ),
            nameMatcher="/usr/lib/*/librebootgnoi.*",
            sourceMatcher=SYSMGR_DEB,
        ),
        reason=(
            "In Bazel, rebootbackend links statically against the C++ stdlib and gnoi"
        ),
    ),
    AcceptanceRule(
        id="sysmgr-rebootbackend-static-imports-cpp-stdlib",
        matcher=DiagnosticMatcher(
            codeMatcher=ElfDiagnosticCode(ElfDiagnosticCodeEnum.IMPORT_ADDED),
            nameMatcher="/usr/bin/rebootbackend",
            sourceMatcher=SYSMGR_DEB,
            msgMatcher="*@GLIBCXX_*",
        ),
        reason=(
            "In Bazel, rebootbackend links statically against the C++ stdlib and gnoi"
            "Therefore, it's going to import more symbols."
        ),
        comment="Scoped to the C++ stdlib just to test the rules engine",
    ),
    AcceptanceRule(
        id="sysmgr-rebootbackend-static-imports-all",
        matcher=DiagnosticMatcher(
            codeMatcher=ElfDiagnosticCode(ElfDiagnosticCodeEnum.IMPORT_ADDED),
            nameMatcher="/usr/bin/rebootbackend",
            sourceMatcher=SYSMGR_DEB,
        ),
        reason=(
            "In Bazel, rebootbackend links statically against the C++ stdlib and gnoi"
            "Therefore, it's going to import more symbols."
        ),
    ),
)
