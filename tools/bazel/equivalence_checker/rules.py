"""Differences between the Make and Bazel builds that are accepted as expected.

Each rule names a difference the two builds produce on purpose, and says why.
Any diagnostic that is not accepted by a rule here will fail the run.
"""

from diagnostics import Codes, Modifier
from rules_engine import AcceptanceRule, DiagnosticMatcher, Rules

SYSMGR_DEB = "@sonic-sysmgr//:sysmgr_deb"

RULES = Rules(
    AcceptanceRule(
        id="excluded-by-tag",
        matcher=DiagnosticMatcher(code=Codes.EXCLUDED_BY_TAG),
        reason=(
            "The target carries the exclusion tag, so it was deliberately left out "
            "of the comparison and has nothing to answer for."
        ),
    ),
    AcceptanceRule(
        id="sysmgr-librebootgnoi-not-shipped",
        matcher=DiagnosticMatcher(
            code=Codes.MAKE_ONLY,
            name="/usr/lib/*/librebootgnoi.*",
            source=SYSMGR_DEB,
        ),
        reason="In Bazel, rebootbackend links statically against the C++ stdlib and gnoi",
    ),
    AcceptanceRule(
        id="sysmgr-rebootbackend-static-imports-all",
        matcher=DiagnosticMatcher(
            code=Codes.IMPORT_ADDED,
            name="/usr/bin/rebootbackend",
            source=SYSMGR_DEB,
        ),
        reason=(
            "In Bazel, rebootbackend links statically against the C++ stdlib and gnoi. "
            "Therefore, it's going to import more symbols."
        ),
    ),
    AcceptanceRule(
        id="sysmgr-rebootbackend-static-debug-functions",
        matcher=DiagnosticMatcher(
            code=Codes.FUNCTION_ADDED,
            name="/usr/bin/rebootbackend",
            source=SYSMGR_DEB,
            modifier=Modifier.DEBUG,
        ),
        reason=(
            "In Bazel, rebootbackend links statically against the C++ stdlib, protobuf "
            "and Abseil, so their functions land in its own debug information."
        ),
    ),
)
