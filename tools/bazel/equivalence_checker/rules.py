"""Differences between the Make and Bazel builds that are accepted as expected.

Each rule names a difference the two builds produce on purpose, and says why.
Any diagnostic that is not accepted by a rule here will fail the run.
"""

from diagnostics import Codes, Modifier
from rules_engine import AcceptanceRule, DiagnosticMatcher, Rules

SYSMGR_DEB = "@sonic-sysmgr//:sysmgr_deb"

REBOOTBACKEND = lambda code, modifier=None: DiagnosticMatcher(
        code=code,
        name="/usr/bin/rebootbackend",
        source=SYSMGR_DEB,
        modifier=modifier,
)

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
        id="accept-debian-changelogs",
        matcher=DiagnosticMatcher(
            name="*/changelog.gz",
            code=Codes.MAKE_ONLY,
        ),
        reason="We don't ship changelogs in Bazel-built debs.",
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
        matcher=REBOOTBACKEND(Codes.IMPORT_ADDED),
        reason=(
            "In Bazel, rebootbackend links statically against the C++ stdlib and gnoi. "
            "Therefore, it's going to import more symbols."
        ),
    ),
    AcceptanceRule(
        id="sysmgr-rebootbackend-init-array",
        matcher=REBOOTBACKEND(Codes.STARTUP_CALLBACK),
        reason=(
            "In Bazel, rebootbackend links statically against the C++ stdlib and gnoi. "
            "Therefore, it's going to call a lot more startup callbacks."
        ),
    ),
    AcceptanceRule(
        id="sysmgr-rebootbackend-static-debug-functions",
        matcher=REBOOTBACKEND(Codes.FUNCTION_ADDED, modifier=Modifier.DEBUG),
        reason=(
            "In Bazel, rebootbackend links statically against the C++ stdlib, protobuf "
            "and Abseil, so their functions land in its own debug information."
        ),
    ),
)
