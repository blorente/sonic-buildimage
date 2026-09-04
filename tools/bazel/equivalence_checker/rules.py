"""Differences between the Make and Bazel builds that are accepted as expected.

Each rule names a difference the two builds produce on purpose, and says why.
Any diagnostic that is not accepted by a rule here will fail the run.
"""

from diagnostics import Codes, Modifier
from rules_engine import AcceptanceRule, DiagnosticMatcher, Rules

SYSMGR_DEB = "@sonic-sysmgr//:sysmgr_deb"

REBOOTBACKEND = lambda code, modifier=None, msg="*": DiagnosticMatcher(
        code=code,
        name="/usr/bin/rebootbackend",
        source=SYSMGR_DEB,
        modifier=modifier,
        msg=msg,
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
        id="sysmgr-rebootbackend-static-gnoi-imports",
        # `4gnoi` is the gnoi namespace as Itanium mangling spells it, so this
        # reaches every gnoi symbol, including protobuf templates instantiated
        # on a gnoi type.
        matcher=REBOOTBACKEND(Codes.IMPORT_REMOVED, msg="*4gnoi*"),
        reason=(
            "In Bazel, rebootbackend links the gnoi protos statically, so their "
            "symbols are defined in the binary instead of imported from "
            "librebootgnoi.so.0, which Bazel does not ship."
        ),
    ),
    AcceptanceRule(
        id="sysmgr-rebootbackend-static-protobuf-imports",
        matcher=REBOOTBACKEND(Codes.IMPORT_REMOVED, msg="*6google8protobuf*"),
        reason=(
            "Bazel builds against protobuf 33.4, while Debian trixie ships 3.21.12 as "
            "libprotobuf.so.32. The util::status_internal::Status API these symbols "
            "belong to is gone in 33.4, replaced by absl::Status, so there is no shared "
            "protobuf both builds can link. Bazel links it statically instead."
        ),
    ),
)
