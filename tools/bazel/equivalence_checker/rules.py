"""Differences between the Make and Bazel builds that are accepted as expected.

Each rule names a difference the two builds produce on purpose, and says why.
Any diagnostic that is not accepted by a rule here will fail the run.
"""

from diagnostics import Codes, Modifier
from rules_engine import AcceptanceRule, DiagnosticMatcher, Rules, literal, ANY_CODE

REBOOTBACKEND = lambda codes, modifier=None, msg="*", msg_exclude=(): DiagnosticMatcher(
        codes=codes,
        name="/usr/bin/rebootbackend",
        modifier=modifier,
        msg=msg,
        msg_exclude=msg_exclude,
)

# The ELF codes that report facts about one symbol,
# as opposed to the whole binary (e.g. DT_NEEDED discrepancies).
SYMBOL_CODES = (
    Codes.EXPORT_ADDED,
    Codes.EXPORT_CHANGED,
    Codes.EXPORT_REMOVED,
    Codes.FUNCTION_ADDED,
    Codes.FUNCTION_REMOVED,
    Codes.IMPORT_ADDED,
    Codes.IMPORT_CHANGED,
    Codes.IMPORT_REMOVED,
)


# Rules that we need because we link libprotobuf and Abseil statically in Bazel.
REBOOTBACKEND_STATIC_LINK_RULES = [
    AcceptanceRule(
        id="sysmgr-librebootgnoi-not-shipped",
        matcher=DiagnosticMatcher(
            codes=Codes.MAKE_ONLY,
            name="/usr/lib/*/librebootgnoi.*",
        ),
        reason="In Bazel, rebootbackend links statically against the C++ stdlib, protobuf, and gnoi",
    ),
    AcceptanceRule(
        id="sysmgr-rebootbackend-init-array-count",
        # We include the counts in the message so that we notice when we introduce new dependencies.
        matcher=REBOOTBACKEND(
            codes=Codes.STARTUP_CALLBACK,
            msg=literal('{"category": "startup-callback", "section": ".init_array", "name": ".init_array.count", "left": 4, "right": 21, "detail": "The number of ordered loader callbacks changed."}'),
        ),
        reason=(
            "Every generated .pb.cc registers its descriptors from a loader callback. "
            "Bazel links the gnoi protos and protobuf into the binary, so it runs many more inits than Make."
        ),
    ),
    AcceptanceRule(
        id="sysmgr-rebootbackend-dynamic-needed",
        matcher=REBOOTBACKEND(
            codes=Codes.DEPENDENCY,
            # We include the full lists in the message so that we notice when we introduce new dependencies.
            msg=literal('{"category": "dependency", "section": ".dynamic", "name": "dynamic.needed", "left": ["libswsscommon.so.0", "libdbus-c++-1.so.0", "libprotobuf.so.32", "librebootgnoi.so.0", "libhiredis.so.1.1.0", "libstdc++.so.6", "libgcc_s.so.1", "libc.so.6"], "right": ["libhiredis.so.1.1.0", "libswsscommon.so.0", "libdbus-c++-1.so.0", "libm.so.6", "libstdc++.so.6", "libgcc_s.so.1", "libc.so.6", "ld-linux-x86-64.so.2"]}'),
        ),
        reason=(
            "Bazel links protobuf, Abseil, gnoi and the C++ runtime into rebootbackend."
        ),
    ),
    AcceptanceRule(
        id="sysmgr-rebootbackend-os-abi",
        matcher=REBOOTBACKEND(
            codes=Codes.ELF,
            msg=literal('{"category": "elf", "section": "<elf-header>", "name": "elf.os_abi", "left": "UNIX - System V", "right": "UNIX - GNU"}'),
        ),
        reason=(
            "STB_GNU_UNIQUE is a GNU extension, brought in by the statically linked protobuf and Abseil. "
            "Because of that, the linker stamps the header's OS/ABI byte as GNU."
        ),
    ),
    AcceptanceRule(
        id="sysmgr-rebootbackend-tls-segment",
        matcher=REBOOTBACKEND(
            codes=Codes.RUNTIME,
            msg=literal('{"category": "runtime", "section": "<program-headers>", "name": "runtime.tls", "left": "<absent>", "right": "R"}'),
        ),
        reason=(
            "protobuf and Abseil declare thread-local variables, which end up in this binary's PT_TLS segment."
        ),
    ),
    AcceptanceRule(
        id="sysmgr-rebootbackend-glibc-version-floor",
        matcher=REBOOTBACKEND(
            codes=Codes.RUNTIME_VERSION,
            msg=(
                literal('{"category": "runtime-version", "section": ".gnu.version_r", "name": "versions.required.libc.so.6", "left": ["GLIBC_2.14", "GLIBC_2.2.5", "GLIBC_2.3.4", "GLIBC_2.34", "GLIBC_2.4"], "right": ["GLIBC_2.10", "GLIBC_2.14", "GLIBC_2.16", "GLIBC_2.17", "GLIBC_2.2.5", "GLIBC_2.32", "GLIBC_2.34", "GLIBC_2.38", "GLIBC_2.4"], "detail": "Bazel raises or adds a runtime symbol-version requirement."}'),
                literal('{"category": "runtime-version", "section": ".gnu.version_r", "name": "versions.required.libm.so.6", "left": [], "right": ["GLIBC_2.2.5", "GLIBC_2.29"], "detail": "Bazel raises or adds a runtime symbol-version requirement."}'),
                literal('{"category": "runtime-version", "section": ".gnu.version_r", "name": "versions.required.ld-linux-x86-64.so.2", "left": [], "right": ["GLIBC_2.3"], "detail": "Bazel raises or adds a runtime symbol-version requirement."}'),
            ),
        ),
        reason=(
            "We accept GLIBC version floor raises up to 2.38. "
            "libprotobuf32, the one that Make ships, also requires 2.38, "
            "and we just surfaced that in rebootbackend by statically linking against protobuf."
        ),
    ),
    AcceptanceRule(
        id="sysmgr-rebootbackend-libgcc-version-floor",
        matcher=REBOOTBACKEND(
            codes=Codes.RUNTIME_VERSION,
            msg=literal('{"category": "runtime-version", "section": ".gnu.version_r", "name": "versions.required.libgcc_s.so.1", "left": ["GCC_3.0"], "right": ["GCC_3.0", "GCC_3.4"], "detail": "Bazel raises or adds a runtime symbol-version requirement."}'),
        ),
        reason=(
            "By linking statically we accept a libgcc builtin that raises the floor, __popcountdi2."
            "It arrived in GCC_3.4. Its import is already accepted as a third-party symbol."
        ),
    ),
    AcceptanceRule(
        id="sysmgr-rebootbackend-third-party-symbols",
        matcher=REBOOTBACKEND(
            codes=SYMBOL_CODES,
            # The symbols rebootbackend's own sources define, mangled spells them.
            # Everything else in the binary got there through a static link.
            msg_exclude=(
                '*"name": "_ZN13rebootbackend*',
                '*"name": "_ZN15HostServiceDbus*',
                '*"name": "main"*',
                '*"name": "_GLOBAL__sub_I_interfaces.cpp"*',
                '*"name": "_GLOBAL__sub_I_rebootbackend.cpp"*',
                '*"name": "_GLOBAL__sub_I_rebootbe.cpp"*',
                '*"name": "_GLOBAL__sub_I_reboot_thread.cpp"*',
            ),
        ),
        reason=(
            "Bazel links protobuf, Abseil, gnoi and the C++ runtime into rebootbackend."
            "Only the symbols rebootbackend's own sources define are compared."
        ),
        comment=(
            "We choose to statically link these libraries because they need different versions in Bazel and Make, "
            "so we would have to include two runtimes in the image anyway, thus eating any size gains."
            "The stripped, statically linked rebootbackend takes 8.21MB, compared to 0.5MB for the dynamically linked version."
        ),
    ),
]


PIN_NOT_ENFORCED = """
Make records the version it used in files/build/versions/**/versions-deb-*, but it does not hold itself to it.
src/sonic-build-hooks/scripts/pre_run_buildinfo only installs the apt preferences file
when SONIC_VERSION_CONTROL_COMPONENTS contains `deb`, which is not always.
"""

# Differences that exist only because Make and Bazel resolved the same package to
# different versions. Each names the paths and versions it covers, so that the
# next drift fails instead of being absorbed.
UNENFORCED_DEB_PIN_RULES = [
    AcceptanceRule(
        id="accept-openssl-provider-legacy-drift",
        matcher=DiagnosticMatcher(
            codes=Codes.INCOMPLETE,
            name=literal("/usr/lib/x86_64-linux-gnu/ossl-modules/legacy.so"),
        ),
        reason="Make ships openssl-provider-legacy 3.5.7-1~deb13u2 where Bazel ships 3.5.6-1~deb13u2.",
        comment=PIN_NOT_ENFORCED,
    ),
    AcceptanceRule(
        id="accept-libexpat-drift",
        # The versioned sonames carry the version, so a different one stops matching.
        matcher=DiagnosticMatcher(
            codes=(Codes.BAZEL_ONLY, Codes.TARGET_MISMATCH),
            name=(
                literal("/usr/lib/x86_64-linux-gnu/libexpat.so.1"),
                literal("/usr/lib/x86_64-linux-gnu/libexpat.so.1.10.2"),
                literal("/usr/lib/x86_64-linux-gnu/libexpatw.so.1"),
                literal("/usr/lib/x86_64-linux-gnu/libexpatw.so.1.10.2"),
            ),
        ),
        reason=(
            "Make ships libexpat1 2.8.3-1~deb13u1 where Bazel ships 2.7.1-2, so the sonames in the debug image point at the older library."
        ),
        comment=PIN_NOT_ENFORCED,
    ),
]

# Bazel unpacks a package's data.tar and flattens the layers.
# Make runs dpkg, which also executes maintainer scripts, so it ends up with superfluous state.
NO_DPKG_RULES = [
    AcceptanceRule(
        id="accept-dpkg-admin-state",
        matcher=DiagnosticMatcher(
            codes=(Codes.CONTENT_MISMATCH, Codes.MAKE_ONLY),
            source="//dockers/*",
            name=(
                literal("/etc/group"),
                literal("/etc/group-"),
                literal("/etc/gshadow"),
                literal("/etc/gshadow-"),
                literal("/var/cache/debconf/config.dat"),
                literal("/var/cache/debconf/config.dat-old"),
                literal("/var/cache/debconf/templates.dat"),
                literal("/var/cache/debconf/templates.dat-old"),
                literal("/var/lib/dpkg/triggers/File"),
                literal("/var/lib/ucf/hashfile"),
                literal("/var/lib/ucf/registry"),
            ),
        ),
        reason="Bazel runs no maintainer scripts, so this state stays as the base image left it.",
        comment="""
        /etc/group and /etc/gshadow: openssh-client.postinst adds the `_ssh` group.
        /var/cache/debconf: templates registered by maintainer scripts. Both images set DEBIAN_FRONTEND=noninteractive, so nothing reads them.
        /var/lib/dpkg/triggers/File: we don't plan on updating packages once they ship, so this flag is superfluous.
        /var/lib/ucf: empty on both sides.
        """,
    ),
    AcceptanceRule(
        id="accept-update-alternatives-not-replayed",
        matcher=DiagnosticMatcher(
            codes=(Codes.CONTENT_MISMATCH, Codes.MAKE_ONLY),
            source="//dockers/*",
            name="/var/lib/dpkg/alternatives/*",
        ),
        reason=(
            "vim_alternatives_pkg writes the /etc/alternatives symlinks directly instead of registring them."
        ),
    ),
    AcceptanceRule(
        id="accept-dpkg-diversions-not-replayed",
        matcher=DiagnosticMatcher(
            codes=(Codes.CONTENT_MISMATCH, Codes.MAKE_ONLY),
            source="//dockers/*",
            name=(
                literal("/var/lib/dpkg/diversions"),
                literal("/var/lib/dpkg/diversions-old"),
                literal("/usr/share/vim/vim91/doc/help.txt.vim-tiny"),
                literal("/usr/share/vim/vim91/doc/tags.vim-tiny"),
            ),
        ),
        reason="Bazel has no dpkg-divert, so it overwrites directly, where Make renames the archives first.",
        comment="help.txt and tags themselves are byte-identical, it's just the backups that are missing.",
    ),
    AcceptanceRule(
        id="accept-systemd-user-units-not-enabled",
        matcher=DiagnosticMatcher(
            codes=Codes.MAKE_ONLY,
            source="//dockers/*",
            name=(
                "/etc/systemd/user/*",
                "/var/lib/systemd/deb-systemd-user-helper-enabled/*",
            ),
        ),
        reason=(
            "deb-systemd-helper enables ssh-agent.socket from a maintainer script. "
            "Not needed, since we run supervisord anyway."
        ),
    ),
]

RULES = Rules(
    AcceptanceRule(
        id="excluded-by-tag",
        matcher=DiagnosticMatcher(codes=Codes.EXCLUDED_BY_TAG),
        reason=(
            "The target carries the exclusion tag, so it was deliberately left out "
            "of the comparison and has nothing to answer for."
        ),
    ),
    AcceptanceRule(
        id="accept-debian-changelogs",
        matcher=DiagnosticMatcher(
            name="*/changelog.gz",
            codes=Codes.MAKE_ONLY,
        ),
        reason="We don't ship changelogs in Bazel-built debs.",
    ),
    AcceptanceRule(
        id="accept-var-lib-dpkg-info-make-only",
        matcher=DiagnosticMatcher(
            name="/var/lib/dpkg/info/*",
            source="*dockers/*",
            codes=Codes.MAKE_ONLY,
        ),
        reason="Irrelevant entries once we're in the image.",
    ),
    AcceptanceRule(
        id="accept-build-machinery-residue",
        matcher=DiagnosticMatcher(
            codes=(Codes.CONTENT_MISMATCH, Codes.MAKE_ONLY),
            source="//dockers/*",
            # Listed on by one instead of globbed, so that files that can actually cause issues (e.g. rsyslog.conf)
            # will trigger an error when they mismatch.
            name=(
                literal("/cache.tgz"),
                literal("/etc/ld.so.cache"),
                literal("/etc/shadow"),
                literal("/usr/local/lib/python3.13/dist-packages/bitarray-2.8.1.dist-info/RECORD"),
                literal("/usr/local/share/buildinfo/post-versions/purge-versions-deb"),
                literal("/usr/local/share/buildinfo/post-versions/versions-deb-trixie-amd64"),
                literal("/usr/local/share/buildinfo/post-versions/versions-mirror"),
                literal("/usr/local/share/buildinfo/pre-versions/versions-deb-trixie-amd64"),
                literal("/usr/local/share/buildinfo/pre-versions/versions-py3-trixie-amd64"),
                literal("/usr/local/share/buildinfo/sonic-build-hooks_1.0_all.deb"),
                literal("/usr/local/share/buildinfo/versions/versions-deb"),
                literal("/var/cache/ldconfig/aux-cache"),
                literal("/var/lib/apt/extended_states"),
                literal("/var/lib/dpkg/status"),
                literal("/var/lib/dpkg/status-old"),
                literal("/var/log/alternatives.log"),
                literal("/var/log/apt/eipp.log.xz"),
                literal("/var/log/apt/history.log"),
                literal("/var/log/apt/term.log"),
                literal("/var/log/dpkg.log"),
            ),
        ),
        reason=(
            "Bazel assembles layers, so it has no history or logs to record."
        ),
    ),
    AcceptanceRule(
        id="accept-base-image-binaries-without-debug-symbols",
        # Named one at a time, so a new binary losing its debug half is caught.
        #
        # TODO(bazel-ready): ship the dbgsym debs Make already builds.
        # To do that, we'd have to rely on target/dbs, which we don't want to do for now.
        # Or, alternatively, get the debug information from sonic-swss-common.
        matcher=DiagnosticMatcher(
            codes=(Codes.NO_DEBUG, Codes.MAKE_ONLY),
            name=(
                literal("/usr/bin/eventd"),
                literal("/usr/bin/eventdb"),
                literal("/usr/bin/events_tool"),
                literal("/usr/bin/sonic-db-cli"),
                literal("/usr/bin/swssloglevel"),
                literal("/usr/lib/python3/dist-packages/swsscommon/_swsscommon.so.0.0.0"),
                literal("/usr/lib/x86_64-linux-gnu/libsonicdbcli.so.0.0.0"),
                literal("/usr/lib/x86_64-linux-gnu/libswsscommon.so.0.0.0"),
                literal("/usr/lib/x86_64-linux-gnu/libyang.so.3.9.1"),
                literal("/usr/lib/debug/.dwz/x86_64-linux-gnu/libswsscommon.debug"),
                literal("/usr/lib/debug/.dwz/x86_64-linux-gnu/sonic-eventd.debug"),
            ),
        ),
        reason=(
            "We'd have to depend on target/debs to get debug binaries for these, so we don't."
        ),
    ),
    *UNENFORCED_DEB_PIN_RULES,
    *REBOOTBACKEND_STATIC_LINK_RULES,
    *NO_DPKG_RULES,
)
