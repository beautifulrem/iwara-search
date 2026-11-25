from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_DIR = REPO_ROOT / "deploy" / "linux"
SCRIPTS = sorted(
    [*DEPLOY_DIR.glob("*.sh"), *(REPO_ROOT / "deploy" / "docker").glob("*.sh")], key=lambda path: path.name
)


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda path: path.name)
def test_shell_scripts_parse_and_avoid_unsafe_patterns(path: Path):
    subprocess.run(["bash", "-n", str(path)], check=True)
    text = path.read_text(encoding="utf-8")
    assert "eval " not in text
    assert "uv run search-iwara" not in text


def test_all_expected_scripts_exist():
    names = {path.name for path in SCRIPTS}
    assert {
        "install.sh",
        "run-web.sh",
        "run-sync-latest.sh",
        "run-backup.sh",
        "run-alert.sh",
        "common.sh",
    } <= names
    assert {"sync-loop.sh", "backup-loop.sh"} <= names


def test_install_script_pins_uv_version():
    text = (DEPLOY_DIR / "install.sh").read_text(encoding="utf-8")
    assert re.search(r'UV_VERSION="\$\{UV_VERSION:-\d+\.\d+\.\d+\}"', text)
    assert "https://astral.sh/uv/${UV_VERSION}/install.sh" in text
    assert not re.search(r"\|\s*(ba)?sh\b", text)  # download to a file first, never pipe to a shell


def test_dockerfile_pins_base_images_by_digest():
    text = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    images = re.findall(r"^FROM\s+(\S+)", text, flags=re.MULTILINE)
    assert len(images) == 3
    for image in images:
        # literal tag@digest so Dependabot can bump both
        assert re.fullmatch(r"[\w./-]+:[\w.-]+@sha256:[0-9a-f]{64}", image), image


def test_sync_loop_runs_immediately_and_exits_on_sigterm(tmp_path: Path):
    import os
    import signal
    import time

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "synced"
    fake_cli = bin_dir / "search-iwara"
    fake_cli.write_text(
        f'#!/bin/sh\nif [ "$1" = "--version" ]; then echo 0.3.0; exit 0; fi\ntouch {marker}\nexit 0\n',
        encoding="utf-8",
    )
    fake_cli.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "SYNC_INTERVAL_SECONDS": "300",
        "SYNC_JITTER_SECONDS": "0",
        "SYNC_DRIFT_MARKER": str(tmp_path / "drift"),
    }
    proc = subprocess.Popen(["sh", str(REPO_ROOT / "deploy" / "docker" / "sync-loop.sh")], env=env)
    try:
        for _ in range(40):
            if marker.exists():
                break
            time.sleep(0.05)
        assert marker.exists(), "sync-loop did not run initial sync immediately"
        time.sleep(0.1)
        t0 = time.monotonic()
        proc.send_signal(signal.SIGTERM)
        code = proc.wait(timeout=3.0)
        assert code == 0
        assert time.monotonic() - t0 < 1.5
    finally:
        if proc.poll() is None:
            proc.kill()


def test_run_alert_rejects_unsafe_file_webhook(tmp_path: Path):
    import os

    env = {
        **os.environ,
        "APP_DIR": str(REPO_ROOT),
        "SEARCH_IWARA_ALERT_WEBHOOK": "file:///etc/passwd",
    }
    res = subprocess.run(
        ["bash", str(DEPLOY_DIR / "run-alert.sh"), "search-iwara-sync.service"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 1
    assert "refusing unsafe webhook URL" in res.stdout


def test_run_alert_rejects_metadata_ip_and_http_redirect(tmp_path: Path):
    import http.server
    import os
    import threading

    for bad_url in ("https://169.254.169.254/latest/meta-data/", "https://user:pw@example.com/hook"):
        res = subprocess.run(
            ["bash", str(DEPLOY_DIR / "run-alert.sh"), "search-iwara-sync.service"],
            env={**os.environ, "APP_DIR": str(REPO_ROOT), "SEARCH_IWARA_ALERT_WEBHOOK": bad_url},
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 1
        assert "refusing unsafe webhook URL" in res.stdout

    class _RedirectHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest")
            self.end_headers()

        def log_message(self, fmt: str, *args: object) -> None:
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), _RedirectHandler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        res = subprocess.run(
            ["bash", str(DEPLOY_DIR / "run-alert.sh"), "search-iwara-sync.service"],
            env={
                **os.environ,
                "APP_DIR": str(REPO_ROOT),
                "SEARCH_IWARA_ALERT_WEBHOOK": f"http://127.0.0.1:{srv.server_port}/hook",
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 1
        assert "refusing webhook redirect" in res.stdout
    finally:
        srv.shutdown()
        srv.server_close()


def test_sync_loop_forwards_sigterm_to_running_child(tmp_path: Path):
    import os
    import signal
    import time

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    term_flag = tmp_path / "child_got_term"
    fake_cli = bin_dir / "search-iwara"
    fake_cli.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--version" ]; then echo 0.2.2; exit 0; fi\n'
        f"trap 'touch \"{term_flag}\"; exit 143' TERM INT\n"
        "sleep 30 &\n"
        "wait $!\n",
        encoding="utf-8",
    )
    fake_cli.chmod(0o755)
    proc = subprocess.Popen(
        ["sh", str(REPO_ROOT / "deploy" / "docker" / "sync-loop.sh")],
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "SYNC_DRIFT_MARKER": str(tmp_path / ".drift"),
        },
    )
    try:
        for _ in range(30):
            # Wait until child sleep is spawned
            children = subprocess.run(
                ["ps", "--ppid", str(proc.pid), "-o", "pid="], capture_output=True, text=True, check=False
            ).stdout.strip()
            if children:
                break
            time.sleep(0.05)
        proc.send_signal(signal.SIGTERM)
        code = proc.wait(timeout=3)
        assert code == 0
        assert term_flag.exists()
    finally:
        if proc.poll() is None:
            proc.kill()


@pytest.mark.parametrize(
    "path",
    sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"), key=lambda item: item.name),
    ids=lambda item: item.name,
)
def test_github_workflows_pin_actions_by_commit_sha(path: Path):
    text = path.read_text(encoding="utf-8")
    uses = re.findall(r"^\s*-?\s*uses:\s*([^\s#]+)", text, flags=re.MULTILINE)
    assert uses, f"{path.name} has no action steps"
    for ref in uses:
        assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", ref), f"{path.name}: unpinned action {ref}"


def test_release_script_prepare_and_notes(tmp_path: Path):
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("release_script", REPO_ROOT / "scripts" / "release.py")
    assert spec is not None
    assert spec.loader is not None
    rel = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = rel
    spec.loader.exec_module(rel)

    (tmp_path / "search_iwara").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "search-iwara"\nversion = "0.2.2"\n',
        encoding="utf-8",
    )
    (tmp_path / "search_iwara" / "__init__.py").write_text(
        '__version__ = "0.2.2"\n',
        encoding="utf-8",
    )
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n### Added\n- Facet sidebar.\n\n## [0.2.2] - 2026-10-01\n\n### Fixed\n- Nginx.\n",
        encoding="utf-8",
    )

    with pytest.raises(rel.ReleaseError, match="version mismatch"):
        rel.build_notes(tmp_path, raw_version="v0.3.0", repo="owner/repo")

    assert (
        rel.main(["--repo-root", str(tmp_path), "prepare", "0.3.0", "--date", "2026-11-25", "--no-lock"]) == 0
    )
    assert rel.read_versions(tmp_path) == ("0.3.0", "0.3.0")

    notes_file = tmp_path / "notes.md"
    assert (
        rel.main(
            [
                "--repo-root",
                str(tmp_path),
                "notes",
                "v0.3.0",
                "--repo",
                "BeautifulRem/iwara-search",
                "--output",
                str(notes_file),
            ]
        )
        == 0
    )
    notes = notes_file.read_text(encoding="utf-8")
    assert "### Added\n- Facet sidebar." in notes
    assert "ghcr.io/beautifulrem/iwara-search:0.3.0" in notes
    assert "## [0.2.2]" not in notes

    with pytest.raises(rel.ReleaseError, match="already contains"):
        rel.prepare_release(tmp_path, raw_version="0.3.0", release_date="2026-11-25", run_lock=False)
