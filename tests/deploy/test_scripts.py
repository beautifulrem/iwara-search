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
