#!/usr/bin/env python3
"""Release helper for Search Iwara.

Subcommands
-----------
prepare <version>
    Bump ``pyproject.toml`` and ``search_iwara/__init__.py``, stamp the
    ``## [Unreleased]`` section in ``CHANGELOG.md`` with ``<version>`` and
    today's date, and refresh ``uv.lock``.

notes <tag-or-version>
    Verify that ``<tag-or-version>`` matches ``pyproject.toml`` and
    ``search_iwara/__init__.py``, then extract that version's release notes
    from ``CHANGELOG.md`` (used by ``.github/workflows/release.yml``).
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
import tomllib
from pathlib import Path

DEFAULT_REPO = "beautifulrem/iwara-search"
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?$")
PYPROJECT_VERSION_RE = re.compile(r'^(version\s*=\s*")([^"]+)(")', flags=re.MULTILINE)
INIT_VERSION_RE = re.compile(r'^(__version__\s*=\s*")([^"]+)(")', flags=re.MULTILINE)
HEADING_RE = re.compile(r"^## \[([^\]]+)\](?:[ \t]*[—–-][ \t]*(\S+))?[ \t]*$", flags=re.MULTILINE)


class ReleaseError(RuntimeError):
    """Raised when version metadata or changelog state is invalid."""


def normalize_version(raw: str) -> str:
    version = raw[1:] if raw.startswith("v") else raw
    if not SEMVER_RE.fullmatch(version):
        raise ReleaseError(f"invalid version '{raw}': expected X.Y.Z or X.Y.Z-(alpha|beta|rc).N")
    return version


def read_versions(repo_root: Path) -> tuple[str, str]:
    pyproject_data = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    pyproject_version = str(pyproject_data["project"]["version"])

    init_text = (repo_root / "search_iwara" / "__init__.py").read_text(encoding="utf-8")
    match = INIT_VERSION_RE.search(init_text)
    if match is None:
        raise ReleaseError("could not find __version__ in search_iwara/__init__.py")
    return pyproject_version, match.group(2)


def extract_changelog_section(changelog_text: str, section: str) -> str:
    matches = list(HEADING_RE.finditer(changelog_text))
    for index, match in enumerate(matches):
        if match.group(1) == section:
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(changelog_text)
            body = changelog_text[start:end].strip()
            if not body:
                raise ReleaseError(f"CHANGELOG.md section [{section}] is empty")
            return body
    raise ReleaseError(f"CHANGELOG.md has no ## [{section}] section")


def format_release_notes(changelog_body: str, *, version: str, repo: str) -> str:
    image_repo = repo.lower()
    install_footer = (
        "\n\n---\n\n"
        "### Install & upgrade\n\n"
        f"- **Docker / Compose (`linux/amd64`, `linux/arm64`):** `ghcr.io/{image_repo}:{version}`\n"
        "- **Linux (`systemd`):** `sudo ./deploy/linux/manage.py update`\n"
        f"- **Verification:** check `SHA256SUMS` or run `gh attestation verify <file> -R {repo}`\n"
    )
    return changelog_body.rstrip() + install_footer


def prepare_release(
    repo_root: Path,
    *,
    raw_version: str,
    release_date: str,
    run_lock: bool = True,
) -> str:
    version = normalize_version(raw_version)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", release_date):
        raise ReleaseError(f"invalid date '{release_date}': expected YYYY-MM-DD")

    changelog_path = repo_root / "CHANGELOG.md"
    changelog_text = changelog_path.read_text(encoding="utf-8")
    existing_sections = {m.group(1) for m in HEADING_RE.finditer(changelog_text)}
    if version in existing_sections:
        raise ReleaseError(f"CHANGELOG.md already contains ## [{version}]")

    unreleased_body = extract_changelog_section(changelog_text, "Unreleased")

    matches = list(HEADING_RE.finditer(changelog_text))
    unreleased_match = next(m for m in matches if m.group(1) == "Unreleased")
    unreleased_idx = matches.index(unreleased_match)
    next_start = (
        matches[unreleased_idx + 1].start() if unreleased_idx + 1 < len(matches) else len(changelog_text)
    )
    updated_changelog = (
        changelog_text[: unreleased_match.start()]
        + f"## [Unreleased]\n\n## [{version}] - {release_date}\n\n{unreleased_body}\n\n"
        + changelog_text[next_start:]
    )

    pyproject_path = repo_root / "pyproject.toml"
    pyproject_text = pyproject_path.read_text(encoding="utf-8")
    updated_pyproject, count_py = PYPROJECT_VERSION_RE.subn(rf"\g<1>{version}\g<3>", pyproject_text, count=1)
    if count_py != 1:
        raise ReleaseError("failed to update project.version in pyproject.toml")

    init_path = repo_root / "search_iwara" / "__init__.py"
    init_text = init_path.read_text(encoding="utf-8")
    updated_init, count_init = INIT_VERSION_RE.subn(rf"\g<1>{version}\g<3>", init_text, count=1)
    if count_init != 1:
        raise ReleaseError("failed to update __version__ in search_iwara/__init__.py")

    pyproject_path.write_text(updated_pyproject, encoding="utf-8")
    init_path.write_text(updated_init, encoding="utf-8")
    changelog_path.write_text(updated_changelog, encoding="utf-8")

    if run_lock:
        subprocess.run(["uv", "lock"], cwd=repo_root, check=True)  # noqa: S607

    return version


def build_notes(repo_root: Path, *, raw_version: str, repo: str) -> str:
    version = normalize_version(raw_version)
    pyproject_version, init_version = read_versions(repo_root)
    if pyproject_version != version or init_version != version:
        raise ReleaseError(
            f"version mismatch for tag '{raw_version}': "
            f"pyproject.toml={pyproject_version}, __init__.py={init_version}"
        )
    changelog_text = (repo_root / "CHANGELOG.md").read_text(encoding="utf-8")
    body = extract_changelog_section(changelog_text, version)
    return format_release_notes(body, version=version, repo=repo)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare or verify a Search Iwara release.")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root directory.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    prep = sub.add_parser("prepare", help="Bump version files and stamp CHANGELOG.md.")
    prep.add_argument("version", help="Release version (e.g. 0.3.0).")
    prep.add_argument(
        "--date",
        default=dt.datetime.now(dt.UTC).date().isoformat(),
        help="Release date in YYYY-MM-DD (default: today UTC).",
    )
    prep.add_argument(
        "--no-lock",
        action="store_true",
        help="Skip running 'uv lock' after updating pyproject.toml.",
    )

    notes = sub.add_parser("notes", help="Verify version parity and output release notes.")
    notes.add_argument("version", help="Tag or version (e.g. v0.3.0 or 0.3.0).")
    notes.add_argument("--repo", default=DEFAULT_REPO, help="GitHub owner/repo.")
    notes.add_argument("--output", type=Path, help="Write Markdown notes to this file.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    repo_root: Path = args.repo_root.resolve()
    try:
        if args.command == "prepare":
            version = prepare_release(
                repo_root,
                raw_version=args.version,
                release_date=args.date,
                run_lock=not args.no_lock,
            )
            sys.stdout.write(
                f"Prepared release {version}.\nNext: review git diff, commit, then tag and push v{version}.\n"
            )
            return 0

        rendered = build_notes(repo_root, raw_version=args.version, repo=args.repo)
        if args.output is not None:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            sys.stdout.write(rendered)
        return 0
    except ReleaseError as exc:
        sys.stderr.write(f"release error: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
