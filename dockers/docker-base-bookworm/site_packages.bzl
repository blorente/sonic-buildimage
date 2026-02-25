load("@rules_python//python:defs.bzl", "PyInfo")
load("@tar.bzl", "mutate", "tar")

def _export_pyinfo(ctx):
    files = []
    for dep in ctx.attr.srcs:
        files.append(dep[PyInfo].transitive_sources)
    return DefaultInfo(files = depset([], transitive = files))

export_py_info = rule(
    implementation = _export_pyinfo,
    attrs = {
        "srcs": attr.label_list(providers = [PyInfo]),
    },
)

def site_packages(name, srcs, **kwargs):
    export_py_info(
        name = name + "_info",
        srcs = srcs,
    )
    tar(
        name = name,
        srcs = [":" + name + "_info"],
        **kwargs
    )
