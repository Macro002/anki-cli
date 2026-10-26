"""Run Anki-Connect's own client-flow and contract tests against anki-cli.

The upstream tests are fetched at a pinned commit (they are GPL-3.0 and are not
vendored here) and executed with a small shim that provides the ``plugin`` module
interfaces they import, backed by a real anki-cli server over HTTP.

    python tests/compat/run.py            # fetch (once) and run
    python tests/compat/run.py -x -k yomitan
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = "https://git.sr.ht/~foosoft/anki-connect"
COMMIT = "62fc13d107c2b02130e503749e9933495c6456fb"
UPSTREAM_TESTS = ["test_yomitan.py", "test_obsidian.py", "test_asbplayer.py", "test_gsm.py", "test_jiten.py",
                  "test_lunatranslator.py", "test_legacy_errors.py", "test_legacy_normalization.py",
                  "legacy_binding_errors.json"]
# Cases that need Anki Desktop itself (Qt reviewer/editor windows, permission dialogs,
# a desktop with no profile loaded) or test Anki-Connect's in-process transport stubs.
DESKTOP_ONLY = ["missing_reviewer_error", "collection_unavailable", "null_result_is_json",
                "block_affected_editors", "permission_context"]
# Replaced by tests_api/test_luna_socket.py, which replays the same flow over a real socket.
REPLACED = ["tests_api/test_lunatranslator.py::test_luna_desktop_get_mining_model_refresh_media_and_overwrite",
            "tests_api/test_lunatranslator.py::test_luna_client_without_key_retains_authentication_error"]


def fetch(cache: Path) -> Path:
    source = cache / "anki-connect"
    if not (source / ".git").exists():
        subprocess.run(["git", "clone", "--quiet", REPO, str(source)], check=True)
    subprocess.run(["git", "-C", str(source), "fetch", "--quiet", "origin", COMMIT], check=False)
    subprocess.run(["git", "-C", str(source), "checkout", "--quiet", COMMIT], check=True)
    return source


def main() -> int:
    here = Path(__file__).resolve().parent
    source = fetch(here.parent.parent / ".cache")
    with tempfile.TemporaryDirectory(prefix="ankicli-compat-") as directory:
        work = Path(directory)
        shutil.copytree(here / "shim", work, dirs_exist_ok=True)
        shutil.copy(source / "api-v1.schema.json", work / "api-v1.schema.json")
        for name in UPSTREAM_TESTS:
            shutil.copy(source / "tests_api" / name, work / "tests_api" / name)
        command = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-o", "addopts=", "-q",
                   "tests_api", "-k", " and ".join(f"not {name}" for name in DESKTOP_ONLY)]
        for case in REPLACED:
            command += ["--deselect", case]
        return subprocess.call(command + sys.argv[1:], cwd=work)


if __name__ == "__main__":
    sys.exit(main())
