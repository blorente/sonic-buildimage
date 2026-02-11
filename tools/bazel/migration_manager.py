#!/usr/bin/env python3
"""Cross-Repository Commit Table Generator.

Recursively traverses Bazel module dependencies via local_path_override
directives and produces a Markdown table showing compatible commit SHAs
across all linked repositories.
"""

import argparse
import json
import os
import re
import subprocess
import sys


def bold_purple(text):
    return f"\033[1;35m{text}\033[0m"


def bold(text):
    return f"\033[1m{text}\033[0m"


def dim(text):
    return f"\033[2m{text}\033[0m"


def format_grep_hit(hit):
    """Style a 'git grep -n' hit line: bold coords, dim content."""
    parts = hit.split(":", 2)
    if len(parts) == 3:
        filename, lineno, content = parts
        return f"    {bold(filename + ':' + lineno)}: {dim(content)}"
    return f"    {hit}"


def git_rev_parse(repo_path, short=False):
    cmd = ["git", "rev-parse"]
    if short:
        cmd.append("--short")
    cmd.append("HEAD")
    try:
        result = subprocess.run(
            cmd, cwd=repo_path, capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def git_grep_todo_bl(repo_path):
    """Return list of 'file:line' hits for 'BL:' in the repo, or [] if none."""
    try:
        result = subprocess.run(
            ["git", "grep", "-n", "--fixed-strings", " BL:"],
            cwd=repo_path, capture_output=True, text=True
        )
        # exit code 0 = matches found, 1 = no matches, anything else = error
        if result.returncode == 0:
            hits = result.stdout.strip().splitlines()
            # Ignore binary file notifications ("Binary file X matches")
            # and hits in migration_manager.py itself.
            hits = [
                h for h in hits
                if not h.startswith("Binary file ")
                and not h.split(":")[0].endswith("migration_manager.py")
            ]
            return hits
        return []
    except OSError:
        return []


def git_grep_todo_bazel_ready(repo_path):
    """Return list of 'file:line' hits for 'TODO(bazel-ready)' in the repo, or [] if none."""
    try:
        result = subprocess.run(
            ["git", "grep", "-n", "--fixed-strings", "TODO(bazel-ready)"],
            cwd=repo_path, capture_output=True, text=True
        )
        if result.returncode == 0:
            return result.stdout.strip().splitlines()
        return []
    except OSError:
        return []


def git_has_uncommitted_changes(repo_path):
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_path, capture_output=True, text=True, check=True
        )
        return bool(result.stdout.strip())
    except subprocess.CalledProcessError:
        return False


def git_branch(repo_path):
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_path, capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def git_create_tag(repo_path, tag_name):
    """Create a lightweight tag in repo_path. Returns (True, '') on success or (False, err) on failure."""
    try:
        result = subprocess.run(
            ["git", "tag", tag_name],
            cwd=repo_path, capture_output=True, text=True
        )
        if result.returncode == 0:
            return True, ""
        return False, result.stderr.strip()
    except OSError as e:
        return False, str(e)


def run_tests(repo_path):
    """Run test_working_targets.sh from repo_path. Returns True on success."""
    script = os.path.join(os.path.dirname(os.path.realpath(__file__)), "test_working_targets.sh")
    if not os.path.isfile(script):
        print(f"Error: could not find test script at {script}", file=sys.stderr)
        return False
    print("Running test_working_targets.sh ...", file=sys.stderr)
    result = subprocess.run([script], cwd=repo_path)
    return result.returncode == 0


def git_push_tag(repo_path, remote, tag_name):
    """Push tag_name to remote in repo_path. Returns (True, '') on success or (False, err) on failure."""
    try:
        result = subprocess.run(
            ["git", "push", remote, tag_name],
            cwd=repo_path, capture_output=True, text=True
        )
        if result.returncode == 0:
            return True, ""
        return False, result.stderr.strip()
    except OSError as e:
        return False, str(e)


REPO_NAME_OVERRIDES = {
    "sonic-sairedis/SAI": "opencompute/SAI",
}


def repo_name(abs_path):
    parent = os.path.basename(os.path.dirname(abs_path))
    name = os.path.basename(abs_path)
    default = f"{parent}/{name}"
    return REPO_NAME_OVERRIDES.get(default, default)


def parse_local_path_overrides(module_bazel_path):
    """Extract path values from local_path_override directives."""
    try:
        with open(module_bazel_path, "r") as f:
            content = f.read()
    except OSError:
        return []

    paths = []
    pattern = re.compile(
        r'local_path_override\s*\([^)]*?path\s*=\s*"([^"]+)"', re.DOTALL
    )
    for match in pattern.finditer(content):
        paths.append(match.group(1))
    return paths


def process_repo(repo_path, visited, results, dirty_repos, todo_hits,
                 bazel_ready_hits, short=False, include_branch=False, parent_path=None):
    abs_path = os.path.realpath(repo_path)

    if abs_path in visited:
        return
    visited.add(abs_path)

    if not os.path.isdir(abs_path):
        print(f"Warning: path does not exist: {abs_path}", file=sys.stderr)
        return

    sha = git_rev_parse(abs_path, short=short)
    if sha is None:
        print(f"Warning: not a git repository: {abs_path}", file=sys.stderr)
        return

    if git_has_uncommitted_changes(abs_path):
        dirty_repos.append(abs_path)

    bl_hits = git_grep_todo_bl(abs_path)
    if bl_hits:
        todo_hits[abs_path] = bl_hits

    br_hits = git_grep_todo_bazel_ready(abs_path)
    if br_hits:
        bazel_ready_hits[abs_path] = br_hits

    # Skip subdirectories that live under src/ of the parent repo.
    if parent_path:
        parent_abs = os.path.realpath(parent_path)
        src_dir = os.path.join(parent_abs, "src") + os.sep
        if abs_path.startswith(src_dir):
            return

    entry = {
        "repository": repo_name(abs_path),
        "path": abs_path,
        "commit": sha,
        "is_working": not bool(bl_hits),
        "is_bazel_ready": not bool(br_hits),
    }
    if include_branch:
        entry["branch"] = git_branch(abs_path) or "unknown"
    results.append(entry)

    module_bazel = os.path.join(abs_path, "MODULE.bazel")
    if not os.path.isfile(module_bazel):
        print(f"Warning: no MODULE.bazel in {abs_path}", file=sys.stderr)
        return

    for rel_path in parse_local_path_overrides(module_bazel):
        dep_path = os.path.join(abs_path, rel_path)
        process_repo(dep_path, visited, results, dirty_repos, todo_hits,
                     bazel_ready_hits, short=short,
                     include_branch=include_branch, parent_path=abs_path)


def format_markdown(results, include_branch=False):
    headers = ["Repository", "Commit"]
    if include_branch:
        headers.append("Branch")

    keys = ["repository", "commit"]
    if include_branch:
        keys.append("branch")

    # Compute column widths from headers and data.
    widths = [len(h) for h in headers]
    for r in results:
        for i, k in enumerate(keys):
            widths[i] = max(widths[i], len(r[k]))

    def row(cells):
        padded = [c.ljust(w) for c, w in zip(cells, widths)]
        return "| " + " | ".join(padded) + " |"

    lines = [
        row(headers),
        "|" + "|".join("-" * (w + 2) for w in widths) + "|",
    ]
    for r in results:
        lines.append(row([r[k] for k in keys]))
    return "\n".join(lines)


def format_checkpoint_markdown(results, todo_bl_hits, todo_bazel_ready_hits,
                                include_branch=False):
    import datetime
    date_str = datetime.date.today().isoformat()
    lines = [f"# Checkpoint -- {date_str}", ""]

    headers = ["Repository", "Commit"]
    keys = ["repository", "commit"]
    if include_branch:
        headers.append("Branch")
        keys.append("branch")
    headers += ["Working", "Bazel-Ready"]

    # Variable-width columns: compute from data
    widths = [len(h) for h in headers[:len(keys)]]
    for r in results:
        for i, k in enumerate(keys):
            widths[i] = max(widths[i], len(r[k]))
    # Status columns: fixed to header width
    status_widths = [len("Working"), len("Bazel-Ready")]
    all_widths = widths + status_widths

    CHECK, CROSS = "✓", "✗"

    def row(cells):
        padded = [c.ljust(w) for c, w in zip(cells, all_widths)]
        return "| " + " | ".join(padded) + " |"

    lines.append(row(headers))
    lines.append("|" + "|".join("-" * (w + 2) for w in all_widths) + "|")
    for r in results:
        cells = [r[k] for k in keys] + [
            CHECK if r["is_working"] else CROSS,
            CHECK if r["is_bazel_ready"] else CROSS,
        ]
        lines.append(row(cells))

    if todo_bl_hits or todo_bazel_ready_hits:
        lines += ["", "## Issues", ""]
        for section_title, hits_dict in [
            ("### TODO BL: markers", todo_bl_hits),
            ("### TODO(bazel-ready) markers", todo_bazel_ready_hits),
        ]:
            if hits_dict:
                lines.append(section_title)
                lines.append("")
                for repo_path, hits in hits_dict.items():
                    lines.append(f"**{repo_name(repo_path)}** (`{repo_path}`)")
                    lines.append("")
                    lines.append("```")
                    lines.extend(hits)
                    lines.append("```")
                    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Generate a commit table from Bazel local_path_override dependencies"
    )
    parser.add_argument("repo", help="Path to the central repository")
    parser.add_argument("--short", action="store_true",
                        help="Use short commit SHAs")
    parser.add_argument("--include-branch", action="store_true",
                        help="Also show current branch name")
    parser.add_argument("--json", action="store_true", dest="output_json",
                        help="Output as JSON instead of Markdown")
    parser.add_argument("--checkpoint", action="store_true",
                        help="Output a checkpoint Markdown document with status columns "
                             "(does not fail on BL: or bazel-ready markers)")
    parser.add_argument("--tag", action="store_true",
                        help="When used with --checkpoint, create a 'checkpoint-<date>' git tag "
                             "in every repository (only if all repos are clean)")
    parser.add_argument("--push-remote", metavar="REMOTE",
                        help="When used with --tag, push the created tags to this remote "
                             "(e.g. 'origin')")
    parser.add_argument("--run-tests", action="store_true",
                        help="Run test_working_targets.sh before creating a checkpoint "
                             "(tests always run before tagging)")
    args = parser.parse_args()

    results = []
    visited = set()
    dirty_repos = []
    todo_hits = {}
    bazel_ready_hits = {}
    process_repo(args.repo, visited, results, dirty_repos, todo_hits,
                 bazel_ready_hits, short=args.short, include_branch=args.include_branch)

    if args.checkpoint:
        if args.run_tests and not run_tests(args.repo):
            print("Aborting checkpoint: tests failed.", file=sys.stderr)
            sys.exit(1)

        if args.output_json:
            print(json.dumps(results, indent=2))
        else:
            print(format_checkpoint_markdown(
                results, todo_hits, bazel_ready_hits,
                include_branch=args.include_branch
            ))

        if args.tag:
            if dirty_repos:
                print("Skipping tags: the following repositories have uncommitted changes:",
                      file=sys.stderr)
                for path in dirty_repos:
                    print(f"  {bold_purple(path)}", file=sys.stderr)
            elif not run_tests(args.repo):
                print("Skipping tags: tests failed.", file=sys.stderr)
            else:
                import datetime
                tag_name = f"checkpoint-{datetime.date.today().isoformat()}"
                for r in results:
                    ok, err = git_create_tag(r["path"], tag_name)
                    if ok:
                        print(f"Tagged {r['repository']} with {tag_name}", file=sys.stderr)
                    else:
                        print(f"Warning: could not tag {r['repository']}: {err}", file=sys.stderr)
                        continue
                    if args.push_remote:
                        ok, err = git_push_tag(r["path"], args.push_remote, tag_name)
                        if ok:
                            print(f"Pushed {tag_name} in {r['repository']} to {args.push_remote}",
                                  file=sys.stderr)
                        else:
                            print(f"Warning: could not push tag in {r['repository']}: {err}",
                                  file=sys.stderr)
        return

    errors = False

    if dirty_repos:
        print("Error: the following repositories have uncommitted changes:", file=sys.stderr)
        for path in dirty_repos:
            print(f"  {bold_purple(path)}", file=sys.stderr)
        errors = True

    if todo_hits:
        print("Error: the following repositories contain 'BL:' markers:", file=sys.stderr)
        for path, hits in todo_hits.items():
            print(f"  {bold_purple(path)}", file=sys.stderr)
            for hit in hits:
                print(format_grep_hit(hit), file=sys.stderr)
        errors = True

    if errors:
        sys.exit(1)

    if args.output_json:
        print(json.dumps(results, indent=2))
    else:
        print(format_markdown(results, include_branch=args.include_branch))


if __name__ == "__main__":
    main()
