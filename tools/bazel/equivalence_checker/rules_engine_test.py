"""Tests for the rule layer: matching a diagnostic, and classifying a run's worth of them.

Everything is built in memory, against the fixture rules below rather than the ones we
ship: what is under test is the machinery, not which differences the project has
decided to live with.

Each table is walked by one `subTest` loop. A row holds every diagnostic that belongs
to one question, with the outcome expected of each, so a new case is usually another
entry in a row rather than a row of its own.
"""

import unittest

import rules_engine
from diagnostics import ArtifactIdentifier, Codes, Diagnostic, Modifier
from rules_engine import ANY_CODE, AcceptanceRule, DiagnosticMatcher, Rules

DEB = "@example//:example_deb"
OTHER_DEB = "@other//:other_deb"
BINARY = "/usr/bin/example"

DEBUG = frozenset({Modifier.DEBUG})
RUNTIME = frozenset({Modifier.RUNTIME})


def diagnostic(
    code: Codes,
    name: str = "/usr/bin/thing",
    source: str | None = DEB,
    msg: str = "",
    modifiers: frozenset[Modifier] = frozenset(),
) -> Diagnostic:
    """One diagnostic, with its source artifact named by label alone.

    `code` is a member of the flat enum, whose value is the code already wrapped
    for whichever family it came from.
    """
    within = (
        None
        if source is None
        else ArtifactIdentifier(name=source, source=None, modifiers=frozenset())
    )
    return Diagnostic(ArtifactIdentifier(name, within, modifiers), code.value, msg)


# --- The rules under test -------------------------------------------------
#
# One per way a matcher can narrow, so a rule set exercising the whole matcher is
# on hand for the tables below.

TAGGED = AcceptanceRule(
    id="tagged",
    matcher=DiagnosticMatcher(code=Codes.EXCLUDED_BY_TAG),
    reason="a code, and nothing else",
)
CHANGELOGS = AcceptanceRule(
    id="changelogs",
    matcher=DiagnosticMatcher(code=Codes.MAKE_ONLY, name="*/changelog.gz"),
    reason="a code and a name glob",
)
ONE_LIBRARY = AcceptanceRule(
    id="one-library",
    matcher=DiagnosticMatcher(
        code=Codes.MAKE_ONLY, name="/usr/lib/*/libexample.*", source=DEB
    ),
    reason="a code, a name glob and a source",
)
ADDED_IMPORTS = AcceptanceRule(
    id="added-imports",
    matcher=DiagnosticMatcher(code=Codes.IMPORT_ADDED, name=BINARY, source=DEB),
    reason="one code on one binary in one package",
)
DEBUG_FUNCTIONS = AcceptanceRule(
    id="debug-functions",
    matcher=DiagnosticMatcher(
        code=Codes.FUNCTION_ADDED, name=BINARY, source=DEB, modifier=Modifier.DEBUG
    ),
    reason="one half of a pair",
)
ONE_MESSAGE = AcceptanceRule(
    id="one-message",
    matcher=DiagnosticMatcher(code=Codes.SECURITY, msg="*bind_now*"),
    reason="one finding out of the several a code reports",
)
EVERYTHING = AcceptanceRule(
    id="everything", matcher=DiagnosticMatcher(code=ANY_CODE), reason="a catch-all"
)

SAMPLE_RULES = Rules(
    TAGGED, CHANGELOGS, ONE_LIBRARY, ADDED_IMPORTS, DEBUG_FUNCTIONS, ONE_MESSAGE
)


def accepting(found: Diagnostic) -> str | None:
    """The id of the fixture rule that accepts `found`, or None if it fails the run."""
    rule = SAMPLE_RULES.accepting(found)
    return rule.id if rule is not None else None


# --- What a matcher takes:
#     (description, matcher, diagnostics, whether the matcher takes each) ---

MATCHER_CASES = [
    (
        "a matcher takes the code it names, and only that code",
        DiagnosticMatcher(code=Codes.MAKE_ONLY),
        [
            diagnostic(Codes.MAKE_ONLY),
            diagnostic(Codes.BAZEL_ONLY),
            # Two families could one day share a code name, and a rule must not
            # reach across: EXCLUDED_BY_TAG is a collection code, MAKE_ONLY an
            # extraction one.
            diagnostic(Codes.EXCLUDED_BY_TAG),
        ],
        [True, False, False],
    ),
    (
        # One code per family, so ANY_CODE is shown to reach all four.
        "ANY_CODE matches a code from every family",
        DiagnosticMatcher(code=ANY_CODE),
        [
            diagnostic(Codes.IMPORT_ADDED),
            diagnostic(Codes.EXCLUDED_BY_TAG),
            diagnostic(Codes.MAKE_ONLY),
            diagnostic(Codes.CONTENT_MISMATCH),
        ],
        [True, True, True, True],
    ),
    (
        "name, source and msg default to matching everything",
        DiagnosticMatcher(code=ANY_CODE),
        [diagnostic(Codes.MAKE_ONLY, name="/anything", source="@x//:y", msg="text")],
        [True],
    ),
    (
        "the name pattern is a glob that does not spill onto a neighbour",
        DiagnosticMatcher(code=ANY_CODE, name="/usr/lib/*/libexample.*"),
        [
            diagnostic(Codes.MAKE_ONLY, name="/usr/lib/x86_64-linux-gnu/libexample.so.0"),
            diagnostic(Codes.MAKE_ONLY, name="/usr/lib/x86_64-linux-gnu/libother.so.0"),
        ],
        [True, False],
    ),
    (
        "the source pattern is matched against the source artifact",
        DiagnosticMatcher(code=ANY_CODE, source=DEB),
        [
            diagnostic(Codes.MAKE_ONLY, source=DEB),
            diagnostic(Codes.MAKE_ONLY, source=OTHER_DEB),
            # Collection runs before anything is unpacked, so its diagnostics have
            # no source at all.
            diagnostic(Codes.EXCLUDED_BY_TAG, source=None),
        ],
        [True, False, False],
    ),
    (
        "a sourceless diagnostic is still matched by the default source pattern",
        DiagnosticMatcher(code=ANY_CODE),
        [diagnostic(Codes.EXCLUDED_BY_TAG, source=None)],
        [True],
    ),
    (
        "the msg pattern distinguishes two findings of the same code",
        DiagnosticMatcher(code=ANY_CODE, msg="*bind_now*"),
        [
            diagnostic(Codes.SECURITY, msg='{"name": "security.bind_now"}'),
            diagnostic(Codes.SECURITY, msg='{"name": "security.relro"}'),
        ],
        [True, False],
    ),
    (
        "patterns are case sensitive, so a path is not matched by its lowercasing",
        DiagnosticMatcher(code=ANY_CODE, name="/usr/bin/Thing"),
        [diagnostic(Codes.MAKE_ONLY, name="/usr/bin/thing")],
        [False],
    ),
    (
        "a modifier reaches one half of a pair and leaves the other alone",
        DiagnosticMatcher(code=ANY_CODE, modifier=Modifier.DEBUG),
        [
            diagnostic(Codes.FUNCTION_ADDED, modifiers=DEBUG),
            diagnostic(Codes.FUNCTION_ADDED, modifiers=RUNTIME),
            diagnostic(Codes.FUNCTION_ADDED),
        ],
        [True, False, False],
    ),
    (
        "a rule naming no modifier reaches both halves, and neither",
        DiagnosticMatcher(code=ANY_CODE),
        [
            diagnostic(Codes.FUNCTION_ADDED, modifiers=DEBUG),
            diagnostic(Codes.FUNCTION_ADDED, modifiers=RUNTIME),
            diagnostic(Codes.FUNCTION_ADDED),
        ],
        [True, True, True],
    ),
]


# --- Which fixture rule accepts what:
#     (description, diagnostics, the rule id expected to accept each, or None) ---

ACCEPTANCE_CASES = [
    (
        "a rule naming only a code accepts it wherever it turns up",
        [
            diagnostic(Codes.EXCLUDED_BY_TAG, name="//dockers/docker-x:x.gz", source=None),
            diagnostic(Codes.EXCLUDED_BY_TAG, name=BINARY, source=OTHER_DEB),
        ],
        ["tagged", "tagged"],
    ),
    (
        "a name glob picks out one file, leaving its neighbours to fail the run",
        [
            diagnostic(Codes.MAKE_ONLY, name="/usr/share/doc/example/changelog.gz"),
            diagnostic(Codes.MAKE_ONLY, name=BINARY),
        ],
        ["changelogs", None],
    ),
    (
        "a rule narrowed by name and source takes neither on its own",
        [
            diagnostic(
                Codes.MAKE_ONLY,
                name="/usr/lib/x86_64-linux-gnu/libexample.so.0",
                source=DEB,
            ),
            diagnostic(
                Codes.MAKE_ONLY,
                name="/usr/lib/x86_64-linux-gnu/libexample.so.0",
                source=OTHER_DEB,
            ),
            diagnostic(Codes.MAKE_ONLY, name="/usr/lib/x86_64-linux-gnu/libother.so.0"),
        ],
        ["one-library", None, None],
    ),
    (
        "a rule scoped to one package does not accept the same name from another",
        [
            diagnostic(Codes.IMPORT_ADDED, name=BINARY, source=DEB),
            diagnostic(Codes.IMPORT_ADDED, name=BINARY, source=OTHER_DEB),
        ],
        ["added-imports", None],
    ),
    (
        "a rule naming a modifier reaches the debug half only",
        [
            diagnostic(Codes.FUNCTION_ADDED, name=BINARY, source=DEB, modifiers=DEBUG),
            diagnostic(Codes.FUNCTION_ADDED, name=BINARY, source=DEB, modifiers=RUNTIME),
        ],
        ["debug-functions", None],
    ),
    (
        "a msg glob accepts one finding of a code and not the others",
        [
            diagnostic(Codes.SECURITY, msg='{"name": "security.bind_now"}'),
            diagnostic(Codes.SECURITY, msg='{"name": "security.relro"}'),
        ],
        ["one-message", None],
    ),
    (
        "a code no rule names falls through, whichever family it comes from",
        [
            diagnostic(code, name=BINARY, source=DEB, modifiers=RUNTIME)
            for code in (
                Codes.IMPORT_REMOVED,
                Codes.FUNCTION_REMOVED,
                Codes.DIFFERENT_STRIP_LEVELS,
                Codes.BAZEL_ONLY,
                Codes.CONTENT_MISMATCH,
                Codes.MODULE_UNREACHABLE,
            )
        ],
        [None] * 6,
    ),
]


EXCLUDED = diagnostic(Codes.EXCLUDED_BY_TAG, source=None)
CHANGELOG = diagnostic(Codes.MAKE_ONLY, name="/usr/share/doc/x/changelog.gz")
MISMATCH_A = diagnostic(Codes.CONTENT_MISMATCH, name="/a")
MISMATCH_B = diagnostic(Codes.CONTENT_MISMATCH, name="/b")

CLASSIFY_CASES = [
    (
        "a run with no diagnostics classifies to nothing at all",
        [],
        SAMPLE_RULES,
        {},
    ),
    (
        "classify groups by accepting rule, and files the rest under None",
        [EXCLUDED, MISMATCH_A],
        Rules(TAGGED),
        {"tagged": [EXCLUDED], None: [MISMATCH_A]},
    ),
    (
        "diagnostics keep the order they were recorded in, so a report is stable",
        [MISMATCH_A, MISMATCH_B],
        Rules(),
        {None: [MISMATCH_A, MISMATCH_B]},
    ),
    (
        "an empty rule set accepts nothing",
        [EXCLUDED],
        Rules(),
        {None: [EXCLUDED]},
    ),
    (
        "nothing is left over when a rule covers every diagnostic",
        [EXCLUDED, MISMATCH_A],
        Rules(EVERYTHING),
        {"everything": [EXCLUDED, MISMATCH_A]},
    ),
    (
        "the first matching rule wins, so order decides which reason is reported",
        [CHANGELOG],
        Rules(CHANGELOGS, EVERYTHING),
        {"changelogs": [CHANGELOG]},
    ),
    (
        "an earlier catch-all shadows the narrower rule behind it",
        [CHANGELOG],
        Rules(EVERYTHING, CHANGELOGS),
        {"everything": [CHANGELOG]},
    ),
]


class RuleLayer(unittest.TestCase):
    """One method per table. Each row reports on its own, and a failing row does
    not hide the rows after it."""

    def test_a_matcher_takes_what_it_names(self) -> None:
        for description, matcher, found, expected in MATCHER_CASES:
            with self.subTest(description):
                self.assertEqual([matcher.matches(one) for one in found], expected)

    def test_a_rule_accepts_what_its_matcher_takes(self) -> None:
        for description, found, expected in ACCEPTANCE_CASES:
            with self.subTest(description):
                self.assertEqual([accepting(one) for one in found], expected)

    def test_a_run_comes_out_grouped(self) -> None:
        for description, found, applied, expected in CLASSIFY_CASES:
            with self.subTest(description):
                classified = rules_engine.classify(found, applied)
                self.assertEqual(classified, expected)
                # `unaccepted` is the reason a run fails, so it answers for every
                # grouping above.
                self.assertEqual(
                    rules_engine.unaccepted(classified), expected.get(None, [])
                )

    def test_duplicate_rule_ids_are_refused(self) -> None:
        """Two rules under one id would make the report's per-rule counts a lie."""
        with self.assertRaises(ValueError) as refusal:
            _ = Rules(TAGGED, TAGGED)
        self.assertEqual(str(refusal.exception), "duplicate rule ids: tagged")


if __name__ == "__main__":
    unittest.main()
