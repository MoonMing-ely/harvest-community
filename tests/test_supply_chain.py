import re
import tomllib
from pathlib import Path

import harvest


ROOT = Path(__file__).parents[1]


def test_workflow_actions_are_pinned_to_full_commit_shas() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    references = re.findall(r"^\s*- uses:\s+[^@\s]+@([^\s#]+)", workflow, flags=re.MULTILINE)

    assert references
    assert all(re.fullmatch(r"[0-9a-f]{40}", reference) for reference in references)
    assert "permissions:\n  contents: read" in workflow
    assert "    permissions:\n      contents: write" in workflow


def test_dependency_locks_require_hashes_and_launchers_use_them() -> None:
    for name in ("runtime.lock", "dev.lock"):
        lock = (ROOT / "requirements" / name).read_text(encoding="utf-8")
        assert "--hash=sha256:" in lock
        assert "-e " not in lock

    shell_launcher = (ROOT / "run.sh").read_text(encoding="utf-8")
    powershell_launcher = (ROOT / "run.ps1").read_text(encoding="utf-8")
    assert "--require-hashes" in shell_launcher
    assert "--require-hashes" in powershell_launcher
    assert "requirements/runtime.lock" in shell_launcher
    assert "requirements\\runtime.lock" in powershell_launcher


def test_release_packages_standalone_archives_for_every_platform() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    for archive in (
        "harvest-linux-x86_64.tar.gz",
        "harvest-windows-x86_64.zip",
        "harvest-macos-x86_64.tar.gz",
        "harvest-macos-arm64.tar.gz",
    ):
        assert archive in workflow
    assert "Compress-Archive" in workflow
    assert "tar -C dist -czf" in workflow


def test_runtime_and_package_versions_match() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert harvest.__version__ == metadata["project"]["version"]
