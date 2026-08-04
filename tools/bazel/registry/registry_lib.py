"""Shared helpers for generating and publishing sonic-buildimage Bazel modules."""

import configparser
import re
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = (SCRIPT_DIR / "../../..").resolve()


def _extract_module_call(text: str) -> str | None:
    """Return the argument text of the module(...) call, or None if absent."""
    match = re.search(r"module\((.*?)\)", text, re.DOTALL)
    return match.group(1) if match else None


def parse_module_declaration(module_bazel: Path) -> tuple[str, str] | None:
    """Extract (name, version) from a MODULE.bazel's module() declaration.

    Returns None if the file has no module() call or no name field.
    """
    module_call = _extract_module_call(module_bazel.read_text())
    if module_call is None:
        return None

    name_match = re.search(r'name\s*=\s*"([^"]+)"', module_call)
    if name_match is None:
        return None

    version_match = re.search(r'version\s*=\s*"([^"]+)"', module_call)
    version = version_match.group(1) if version_match else "0.0.0"

    return name_match.group(1), version


def rewrite_module_version(text: str, new_version: str) -> str:
    """Return MODULE.bazel text with the module() call's version field set to new_version."""
    match = re.search(r"module\((.*?)\)", text, re.DOTALL)
    if match is None:
        raise ValueError("No module() call found")

    module_call = match.group(1)
    if re.search(r'version\s*=\s*"[^"]*"', module_call):
        new_module_call = re.sub(r'version\s*=\s*"[^"]*"', f'version = "{new_version}"', module_call, count=1)
    else:
        new_module_call = module_call.rstrip() + f',\n    version = "{new_version}",\n'

    return text[: match.start()] + "module(" + new_module_call + ")" + text[match.end() :]


def load_submodule_paths() -> set[str]:
    """Return the set of git submodule paths declared in .gitmodules, relative to repo root."""
    gitmodules = REPO_ROOT / ".gitmodules"
    if not gitmodules.exists():
        return set()

    parser = configparser.ConfigParser()
    parser.read(gitmodules)
    return {
        parser.get(section, "path")
        for section in parser.sections()
        if parser.has_option(section, "path")
    }


def load_submodule_urls() -> dict[str, str]:
    """Return a mapping of git submodule path -> remote URL, from .gitmodules."""
    gitmodules = REPO_ROOT / ".gitmodules"
    if not gitmodules.exists():
        return {}

    parser = configparser.ConfigParser()
    parser.read(gitmodules)
    return {
        parser.get(section, "path"): parser.get(section, "url")
        for section in parser.sections()
        if parser.has_option(section, "path") and parser.has_option(section, "url")
    }


def is_git_submodule(src_path: str, submodule_paths: set[str]) -> bool:
    """Check whether src_path is a git submodule (or lives inside one)."""
    return any(
        src_path == submodule_path or src_path.startswith(submodule_path + "/")
        for submodule_path in submodule_paths
    )


def submodule_root_for(src_path: str, submodule_paths: set[str]) -> str | None:
    """Return the submodule path that src_path is (or lives inside), or None."""
    for submodule_path in submodule_paths:
        if src_path == submodule_path or src_path.startswith(submodule_path + "/"):
            return submodule_path
    return None
