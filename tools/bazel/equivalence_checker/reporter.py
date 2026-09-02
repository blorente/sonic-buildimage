"""Turns the diagnostics a run collected into the report a human reads."""

import collections
import json
from pathlib import Path

import rules
from context import Context


def print_report(ctx: Context, classified: rules.Classified) -> None:
    """Print how many of each diagnostic the run collected."""
    accepted = [(d, rule) for d, rule in classified if rule is not None]
    remaining = [d for d, rule in classified if rule is None]

    print(f"\n{len(ctx.index)} artifacts, {len(ctx.sink.diagnostics)} diagnostics.")

    if accepted:
        by_rule = collections.Counter(rule.id for _, rule in accepted)
        print(f"\n{len(accepted)} accepted:")
        for rule_id, count in by_rule.most_common():
            print(f"    {count:6d}  {rule_id}")

    by_code = collections.Counter(
        str(diagnostic.code.code) for diagnostic in remaining
    )
    print(f"\n{len(remaining)} not accepted:")
    for code, count in by_code.most_common():
        print(f"    {count:6d}  {code}")


def write_report(ctx: Context, classified: rules.Classified, path: Path) -> None:
    """Write every diagnostic the run collected to `path`, as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text(
        json.dumps(
            {
                "artifacts": [
                    {
                        "identifier": str(artifact.identifier),
                        "type": str(artifact.type),
                        "bazel": str(artifact.bazelVersion),
                        "make": str(artifact.makeVersion),
                    }
                    for artifact in ctx.index.artifacts.values()
                ],
                "diagnostics": [
                    {
                        "artifact": str(diagnostic.artifact),
                        "code": str(diagnostic.code.code),
                        "msg": diagnostic.msg,
                        "accepted_by": rule.id if rule is not None else None,
                    }
                    for diagnostic, rule in classified
                ],
            },
            indent=2,
        )
    )
