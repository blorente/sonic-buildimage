
def _extract_tar_impl(ctx):
    tar_file = ctx.path(ctx.attr.archive)

    ctx.extract(
        archive = tar_file,
    )

    ctx.file("BUILD.bazel", ctx.read(ctx.attr.build_file))

extract_tar = repository_rule(
    implementation = _extract_tar_impl,
    attrs = {
        "archive": attr.label(
            allow_single_file = True,
            mandatory = True,
        ),
        "build_file": attr.label(
            allow_single_file = True,
            mandatory = True,
        ),
    },
)
