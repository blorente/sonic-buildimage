"""The machinery for accepting known differences.

What a rule *is*, and how a diagnostic is matched against one. The rules
themselves live in `rules.py`.
"""

import collections
import fnmatch
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TypeAlias

from diagnostics import Codes, Diagnostic, DiagnosticCode


@dataclass(frozen=True)
class AnyCode:
    """Matches every code, whichever family it belongs to."""


ANY_CODE = AnyCode()

# A rule names one code from the flat `Codes` enum, or every code at once.
CodeMatcher: TypeAlias = Codes | AnyCode


@dataclass(frozen=True)
class DiagnosticMatcher:
    """Which diagnostics something applies to.

    `name` and `source` are fnmatch patterns over a ComparableArtifact's name and source.
    `msg` is also an fnmatch pattern, over the diagnostic's own message.
    All three default to everything, so a rule states only what it narrows.
    """

    code: CodeMatcher
    name: str = "*"
    source: str = "*"
    msg: str = "*"

    def matches(self, diagnostic: Diagnostic) -> bool:
        artifact = diagnostic.artifact
        # A diagnostic raised before anything is unpacked has no source artifact.
        source = artifact.source.name if artifact.source is not None else ""
        return (
            self._code_matches(diagnostic.code)
            and fnmatch.fnmatchcase(artifact.name, self.name)
            and fnmatch.fnmatchcase(source, self.source)
            and fnmatch.fnmatchcase(diagnostic.msg, self.msg)
        )

    def _code_matches(self, code: DiagnosticCode) -> bool:
        if isinstance(self.code, AnyCode):
            return True
        # A `Codes` member holds the code already wrapped for its family.
        return code == self.code.value


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


# Diagnostics grouped by the id of the rule that accepts them.
# Unaccepted diagnostics are stored under `None`.
Classified: TypeAlias = dict[str | None, list[Diagnostic]]


def classify(diagnostics: list[Diagnostic], rules: Rules) -> Classified:
    """Group every diagnostic under the rule that accepts it, or under None."""
    grouped: Classified = collections.defaultdict(list)
    for diagnostic in diagnostics:
        rule = rules.accepting(diagnostic)
        grouped[rule.id if rule is not None else None].append(diagnostic)
    return dict(grouped)


def unaccepted(classified: Classified) -> list[Diagnostic]:
    """The diagnostics no rule accepts, which will fail a run."""
    return classified.get(None, [])
