load("@rules_cc//cc:defs.bzl", "cc_library")
load("@tar.bzl", "tar", "mutate")
load("@bazel_skylib//rules:write_file.bzl", "write_file")
load("@rules_deb//distroless:defs.bzl", "flatten")

# =============================================================================
# Generated headers
# =============================================================================

# Generate lib/defs.h from autoconf template.
# On Linux/glibc x86_64 all standard headers exist.
genrule(
    name = "defs_h",
    srcs = ["lib/defs.h.in"],
    outs = ["lib/defs.h"],
    # TODO(bazel-ready): Define NL_DEBUG if necessary, based on configuration.
    # TODO(bazel-ready): Define VERSION from stamping, if necessary.
    cmd = """
        sed \
            -e 's|#undef DISABLE_PTHREADS|/* #undef DISABLE_PTHREADS */|' \
            -e 's|#undef HAVE_DLFCN_H|#define HAVE_DLFCN_H 1|' \
            -e 's|#undef HAVE_INTTYPES_H|#define HAVE_INTTYPES_H 1|' \
            -e 's|#undef HAVE_LIBPTHREAD|#define HAVE_LIBPTHREAD 1|' \
            -e 's|#undef HAVE_STDINT_H|#define HAVE_STDINT_H 1|' \
            -e 's|#undef HAVE_STDIO_H|#define HAVE_STDIO_H 1|' \
            -e 's|#undef HAVE_STDLIB_H|#define HAVE_STDLIB_H 1|' \
            -e 's|#undef HAVE_STRERROR_L|#define HAVE_STRERROR_L 1|' \
            -e 's|#undef HAVE_STRINGS_H|#define HAVE_STRINGS_H 1|' \
            -e 's|#undef HAVE_STRING_H|#define HAVE_STRING_H 1|' \
            -e 's|#undef HAVE_SYS_STAT_H|#define HAVE_SYS_STAT_H 1|' \
            -e 's|#undef HAVE_SYS_TYPES_H|#define HAVE_SYS_TYPES_H 1|' \
            -e 's|#undef HAVE_UNISTD_H|#define HAVE_UNISTD_H 1|' \
            -e 's|#undef LT_OBJDIR|#define LT_OBJDIR ".libs/"|' \
            -e 's|#undef NL_DEBUG|/* #undef NL_DEBUG */|' \
            -e 's|#undef PACKAGE$$|#define PACKAGE "libnl"|' \
            -e 's|#undef PACKAGE_BUGREPORT|#define PACKAGE_BUGREPORT "http://www.infradead.org/~tgr/libnl/"|' \
            -e 's|#undef PACKAGE_NAME|#define PACKAGE_NAME "libnl"|' \
            -e 's|#undef PACKAGE_STRING|#define PACKAGE_STRING "libnl 3.7.0"|' \
            -e 's|#undef PACKAGE_TARNAME|#define PACKAGE_TARNAME "libnl"|' \
            -e 's|#undef PACKAGE_URL|#define PACKAGE_URL "http://www.infradead.org/~tgr/libnl/"|' \
            -e 's|#undef PACKAGE_VERSION|#define PACKAGE_VERSION "3.7.0"|' \
            -e 's|#undef STDC_HEADERS|#define STDC_HEADERS 1|' \
            -e 's|#undef VERSION|#define VERSION "3.7.0"|' \
            $(SRCS) > $@
        echo '#define SYSCONFDIR "/etc/libnl"' >> $@
    """,
)

# =============================================================================
# Flex/Bison generated sources for libnl-route-3
# =============================================================================

FLEX = "$(execpath @flex_bin//:flex)"

# Bison needs m4 at runtime and its data files (skeletons, m4sugar).
# BISON_PKGDATADIR tells bison where to find usr/share/bison from the extracted deb.
M4 = "$(execpath @m4_bin//:m4)"
BISON = "$(execpath @bison_bin//:bison)"
BISON_ENV = "M4={m4} BISON_PKGDATADIR=$$(dirname $$(dirname {bison}))/share/bison {bison}".format(
    m4 = M4,
    bison = BISON,
)

FLEX_TOOLS = ["@flex_bin//:flex"]
BISON_TOOLS = [
    "@bison_bin//:bison",
    "@bison_bin//:bison_data",
    "@m4_bin//:m4",
]

genrule(
    name = "pktloc_grammar",
    srcs = ["lib/route/pktloc_grammar.l"],
    outs = [
        "lib/route/pktloc_grammar.c",
        "lib/route/pktloc_grammar.h",
    ],
    cmd = FLEX + " --header-file=$(location lib/route/pktloc_grammar.h) -o $(location lib/route/pktloc_grammar.c) $(SRCS)",
    tools = FLEX_TOOLS,
)

genrule(
    name = "pktloc_syntax",
    srcs = ["lib/route/pktloc_syntax.y"],
    outs = [
        "lib/route/pktloc_syntax.c",
        "lib/route/pktloc_syntax.h",
    ],
    cmd = BISON_ENV + " -d -o $(location lib/route/pktloc_syntax.c) $(SRCS)",
    tools = BISON_TOOLS,
)

genrule(
    name = "ematch_grammar",
    srcs = ["lib/route/cls/ematch_grammar.l"],
    outs = [
        "lib/route/cls/ematch_grammar.c",
        "lib/route/cls/ematch_grammar.h",
    ],
    cmd = FLEX + " --header-file=$(location lib/route/cls/ematch_grammar.h) -o $(location lib/route/cls/ematch_grammar.c) $(SRCS)",
    tools = FLEX_TOOLS,
)

genrule(
    name = "ematch_syntax",
    srcs = ["lib/route/cls/ematch_syntax.y"],
    outs = [
        "lib/route/cls/ematch_syntax.c",
        "lib/route/cls/ematch_syntax.h",
    ],
    cmd = BISON_ENV + " -d -o $(location lib/route/cls/ematch_syntax.c) $(SRCS)",
    tools = BISON_TOOLS,
)

# =============================================================================
# Header libraries
# =============================================================================

# Public header files for packaging.
filegroup(
    name = "public_header_files",
    srcs = glob(["include/netlink/**/*.h"]),
)

# Public headers: consumers use #include <netlink/...>
cc_library(
    name = "public_headers",
    hdrs = glob(["include/netlink/**/*.h"]),
    strip_include_prefix = "include",
    visibility = ["//visibility:public"],
)

# Private headers used only during compilation of libnl3 libraries.
# Includes netlink-private/, linux-private/, and the generated defs.h.
cc_library(
    name = "private_headers",
    hdrs = glob([
        "include/netlink-private/**/*.h",
        "include/linux-private/**/*.h",
    ]) + [":defs_h"],
    # include/netlink-private/netlink.h uses #include <defs.h>,
    # so we need lib/ in the include path (where defs.h is generated).
    # Also include/linux-private/ provides <linux/...> headers.
    includes = [
        "include",
        "include/linux-private",
        "lib",
    ],
    deps = [":public_headers"],
)

# =============================================================================
# Common build settings
# =============================================================================

LIBNL_COPTS = [
    "-std=gnu11",
    "-fPIC",
    "-Wall",
    "-D_GNU_SOURCE",
    "-O2",
    "-DNDEBUG",
]

LIBNL_LINKOPTS = [
    # TODO BL: Delete if unnecessary
    # "-lpthread",
    # "-lm",
]

# =============================================================================
# Core library: libnl-3
# =============================================================================

cc_library(
    name = "libnl_3",
    srcs = glob(["lib/*.c"]),
    copts = LIBNL_COPTS,
    linkopts = LIBNL_LINKOPTS,
    deps = [
        ":public_headers",
        ":private_headers",
    ],
    visibility = ["//visibility:public"],
)

cc_shared_library(
    name = "libnl_3_shared",
    deps = [":libnl_3"],
    user_link_flags = [
        "-Wl,--version-script=$(location libnl-3.sym)",
        "-Wl,-soname,libnl-3.so.200",
    ],
    additional_linker_inputs = ["libnl-3.sym"],
    visibility = ["//visibility:public"],
)

# =============================================================================
# Generic Netlink library: libnl-genl-3
# =============================================================================

cc_library(
    name = "libnl_genl_3",
    srcs = glob(["lib/genl/*.c"]),
    copts = LIBNL_COPTS,
    deps = [
        ":libnl_3",
        ":private_headers",
    ],
    visibility = ["//visibility:public"],
)

cc_shared_library(
    name = "libnl_genl_3_shared",
    deps = [":libnl_genl_3"],
    dynamic_deps = [":libnl_3_shared"],
    user_link_flags = [
        "-Wl,--version-script=$(location libnl-genl-3.sym)",
        "-Wl,-soname,libnl-genl-3.so.200",
    ],
    additional_linker_inputs = ["libnl-genl-3.sym"],
    visibility = ["//visibility:public"],
)

# =============================================================================
# Route library: libnl-route-3
# =============================================================================

cc_library(
    name = "libnl_route_3",
    srcs = glob(
        [
            "lib/route/*.c",
            "lib/route/**/*.c",
            "lib/fib_lookup/*.c",
        ],
    ) + [
        ":pktloc_grammar",
        ":pktloc_syntax",
        ":ematch_grammar",
        ":ematch_syntax",
    ],
    copts = LIBNL_COPTS,
    # includes adds both source-tree and genfiles-tree variants, so the
    # generated flex/bison headers in lib/route/ and lib/route/cls/ are
    # findable via #include "pktloc_syntax.h" etc.
    includes = [
        "lib/route",
        "lib/route/cls",
    ],
    deps = [
        ":libnl_3",
        ":private_headers",
    ],
    visibility = ["//visibility:public"],
)

cc_shared_library(
    name = "libnl_route_3_shared",
    deps = [":libnl_route_3"],
    dynamic_deps = [":libnl_3_shared"],
    user_link_flags = [
        "-Wl,--version-script=$(location libnl-route-3.sym)",
        "-Wl,-soname,libnl-route-3.so.200",
    ],
    additional_linker_inputs = ["libnl-route-3.sym"],
    visibility = ["//visibility:public"],
)

# =============================================================================
# Netfilter library: libnl-nf-3
# =============================================================================

cc_library(
    name = "libnl_nf_3",
    srcs = glob(["lib/netfilter/*.c"]),
    copts = LIBNL_COPTS,
    deps = [
        ":libnl_3",
        ":libnl_route_3",
        ":private_headers",
    ],
    visibility = ["//visibility:public"],
)

cc_shared_library(
    name = "libnl_nf_3_shared",
    deps = [":libnl_nf_3"],
    dynamic_deps = [
        ":libnl_3_shared",
        ":libnl_route_3_shared",
    ],
    user_link_flags = [
        "-Wl,--version-script=$(location libnl-nf-3.sym)",
        "-Wl,-soname,libnl-nf-3.so.200",
    ],
    additional_linker_inputs = ["libnl-nf-3.sym"],
    visibility = ["//visibility:public"],
)

# TODO(bazel-ready): Parameterize tar files by target architecture.
# TODO(bazel-ready): Generate `.200` packages if needed.
# TODO BL: Make sure everyone links against ehse libraries.

tar(
    name = "libnl-3_pkg",
    srcs = [":libnl_3_shared"],
    mtree = [
        "./usr/lib/x86_64-linux-gnu/libnl-3.so.200 uid=0 gid=0 mode=0755 type=file content=$(location :libnl_3_shared)",
        "./usr/lib/x86_64-linux-gnu/libnl-3.so uid=0 gid=0 mode=0755 type=link link=libnl-3.so.200",
    ],
    visibility = ["//visibility:public"],
)

tar(
    name = "libnl-genl-3_pkg",
    srcs = [":libnl_genl_3_shared"],
    mtree = [
        "./usr/lib/x86_64-linux-gnu/libnl-genl-3.so.200 uid=0 gid=0 mode=0755 type=file content=$(location :libnl_genl_3_shared)",
        "./usr/lib/x86_64-linux-gnu/libnl-genl-3.so uid=0 gid=0 mode=0755 type=link link=libnl-genl-3.so.200",
    ],
    visibility = ["//visibility:public"],
)

tar(
    name = "libnl-route-3_pkg",
    srcs = [":libnl_route_3_shared"],
    mtree = [
        "./usr/lib/x86_64-linux-gnu/libnl-route-3.so.200 uid=0 gid=0 mode=0755 type=file content=$(location :libnl_route_3_shared)",
        "./usr/lib/x86_64-linux-gnu/libnl-route-3.so uid=0 gid=0 mode=0755 type=link link=libnl-route-3.so.200",
    ],
    visibility = ["//visibility:public"],
)

tar(
    name = "libnl-nf-3_pkg",
    srcs = [":libnl_nf_3_shared"],
    mtree = [
        "./usr/lib/x86_64-linux-gnu/libnl-nf-3.so.200 uid=0 gid=0 mode=0755 type=file content=$(location :libnl_nf_3_shared)",
        "./usr/lib/x86_64-linux-gnu/libnl-nf-3.so uid=0 gid=0 mode=0755 type=link link=libnl-nf-3.so.200",
    ],
    visibility = ["//visibility:public"],
)

# =============================================================================
# Packaging: headers tarball
# =============================================================================

tar(
    name = "libnl3-dev_headers",
    srcs = [":public_header_files"],
    mutate = mutate(
        strip_prefix = "include",
        package_dir = "./usr/include/libnl3",
    ),
)

# =============================================================================
# Packaging: pkgconfig files
# =============================================================================

# TODO(bazel-ready): We should use rules_foreign_cc to run cmake and build this file.
# However, because we don't need to override the install directory,
write_file(
    name = "libnl3_pc_generated",
    out = "libnl-3.0.pc",
    content = [
        "prefix=/usr",
        "exec_prefix=${prefix}",
        "libdir=${prefix}/lib/x86_64-linux-gnu",
        "includedir=${prefix}/include/libnl3",
        "",
        "Name: libnl-3.0",
        "Description: Convenience library for netlink sockets",
        "Version: 3.7.0",
        "Libs: -L${libdir} -lnl-3",
        "Libs.private: -lpthread -lm",
        "Cflags: -I${includedir}",
        "",
    ],
)

write_file(
    name = "libnl3_genl_pc_generated",
    out = "libnl-genl-3.0.pc",
    content = [
        "prefix=/usr",
        "exec_prefix=${prefix}",
        "libdir=${prefix}/lib/x86_64-linux-gnu",
        "includedir=${prefix}/include/libnl3",
        "",
        "Name: libnl-genl-3.0",
        "Description: Generic Netlink Library",
        "Version: 3.7.0",
        "Requires: libnl-3.0 >= 3.7.0",
        "Libs: -L${libdir} -lnl-genl-3",
        "Cflags: -I${includedir}",
        "",
    ],
)

write_file(
    name = "libnl3_route_pc_generated",
    out = "libnl-route-3.0.pc",
    content = [
        "prefix=/usr",
        "exec_prefix=${prefix}",
        "libdir=${prefix}/lib/x86_64-linux-gnu",
        "includedir=${prefix}/include/libnl3",
        "",
        "Name: libnl-route-3.0",
        "Description: Routing/link Library",
        "Version: 3.7.0",
        "Requires: libnl-3.0 >= 3.7.0",
        "Libs: -L${libdir} -lnl-route-3",
        "Cflags: -I${includedir}",
        "",
    ],
)

write_file(
    name = "libnl3_nf_pc_generated",
    out = "libnl-nf-3.0.pc",
    content = [
        "prefix=/usr",
        "exec_prefix=${prefix}",
        "libdir=${prefix}/lib/x86_64-linux-gnu",
        "includedir=${prefix}/include/libnl3",
        "",
        "Name: libnl-nf-3.0",
        "Description: Netfilter Netlink Library",
        "Version: 3.7.0",
        "Requires: libnl-3.0 >= 3.7.0",
        "Libs: -L${libdir} -lnl-nf-3",
        "Cflags: -I${includedir}",
        "",
    ],
)

tar(
    name = "libnl3_pkgconfig",
    srcs = [
        ":libnl3_pc_generated",
        ":libnl3_genl_pc_generated",
        ":libnl3_route_pc_generated",
        ":libnl3_nf_pc_generated",
    ],
    mutate = mutate(
        strip_prefix = package_name(),
        package_dir = "./usr/lib/x86_64-linux-gnu/pkgconfig",
    ),
)

# =============================================================================
# Packaging: -dev package tarballs (runtime + headers + pkgconfig)
# =============================================================================

flatten(
    name = "libnl-3-dev_pkg",
    tars = [
        ":libnl-3_pkg",
        ":libnl3-dev_headers",
        ":libnl3_pkgconfig",
    ],
    visibility = ["//visibility:public"],
    deduplicate = True,
)

flatten(
    name = "libnl-genl-3-dev_pkg",
    tars = [
        ":libnl-genl-3_pkg",
        ":libnl-3-dev_pkg",
    ],
    visibility = ["//visibility:public"],
    deduplicate = True,
)

flatten(
    name = "libnl-route-3-dev_pkg",
    tars = [
        ":libnl-route-3_pkg",
        ":libnl-3-dev_pkg",
    ],
    visibility = ["//visibility:public"],
    deduplicate = True,
)

flatten(
    name = "libnl-nf-3-dev_pkg",
    tars = [
        ":libnl-nf-3_pkg",
        ":libnl-3-dev_pkg",
        ":libnl-route-3_pkg",
    ],
    visibility = ["//visibility:public"],
    deduplicate = True,
)
