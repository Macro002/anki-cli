import json
import os
import subprocess
import sys

from test_reliability import free_port, start_server


def run(*args, base=None, url=None, input_text=None, env=None):
    command = [sys.executable, "-m", "ankicli"]
    if base:
        command += ["--base", str(base)]
    if url:
        command += ["--url", url]
    result = subprocess.run(command + list(args), capture_output=True, text=True, input=input_text,
                            env={**{k: v for k, v in os.environ.items() if k != "ANKICLI_URL"}, **(env or {})}, timeout=120)
    return result


def test_direct_mode_commands(tmp_path):
    base = tmp_path / "base"
    assert run("deck", "create", "French::Vocab", base=base).returncode == 0
    out = run("add", "--deck", "French::Vocab", "--tag", "animal", "Front=le chat", "Back=cat", base=base)
    assert out.returncode == 0 and out.stdout.startswith("Added note")
    run("add", "--deck", "French::Vocab", "Front=le chien", "Back=dog", base=base)
    decks = run("decks", base=base).stdout
    assert "French" in decks and "Vocab" in decks
    found = json.loads(run("find", "deck:French", "--json", base=base).stdout)
    assert len(found) == 2
    shown = run("show", found[0], base=base).stdout
    assert "le chat" in shown and "animal" in shown
    called = json.loads(run("call", "notes.search", "query=chien", base=base).stdout)
    assert len(called["ids"]) == 1
    legacy = json.loads(run("call", "deckNames", "--legacy", base=base).stdout)
    assert "French::Vocab" in legacy
    counts = json.loads(run("call", "decks.getCounts", '{"deck": {"name": "French"}}', base=base).stdout)
    assert counts["new"] == 2
    assert "Today:" in run("stats", base=base).stdout
    assert run("check", "--media", base=base).returncode == 0
    assert run("backup", base=base).stdout.startswith("Backup:")
    apkg = tmp_path / "french.apkg"
    assert run("export", str(apkg), "--deck", "French", base=base).returncode == 0 and apkg.exists()
    csv = tmp_path / "notes.csv"
    run("export", str(csv), base=base)
    assert "le chat" in csv.read_text(encoding="utf-8")
    other = tmp_path / "other"
    assert run("import", str(apkg), base=other).returncode == 0
    assert "French" in run("decks", base=other).stdout
    session = run("study", "French", base=base, input_text="\n3\n\n4\nq\n")
    assert "Reviewed 2 card(s)" in session.stdout
    profiles = run("profiles", "create", "Second", base=base).stdout
    assert "* User 1" in profiles and "Second" in profiles
    error = run("show", "123", base=base)
    assert error.returncode == 2 and "not found" in error.stderr.lower()


def test_remote_mode_and_ankicli_url(tmp_path):
    base, port = tmp_path / "base", free_port()
    process = start_server(base, port)
    url = f"http://127.0.0.1:{port}"
    try:
        assert run("add", "Front=remote", url=url).returncode == 0
        assert json.loads(run("find", "remote", "--json", url=url).stdout)
        named = run("find", "remote", "--json", env={"ANKICLI_URL": url})
        assert named.returncode == 0 and json.loads(named.stdout)
        # --base wins over $ANKICLI_URL: the collection is opened, not the server.
        other = run("find", "remote", "--json", base=tmp_path / "other", env={"ANKICLI_URL": url})
        assert other.returncode == 0 and json.loads(other.stdout) == []
    finally:
        process.terminate()
        process.wait(30)


def test_no_server_is_probed_without_a_url(tmp_path, monkeypatch):
    from ankicli import cli, client

    def no_server(*args, **kwargs):
        raise AssertionError("the CLI contacted a server it wasn't given")

    monkeypatch.delenv("ANKICLI_URL", raising=False)
    monkeypatch.setenv("ANKICLI_BASE", str(tmp_path / "base"))
    monkeypatch.setattr(client.Client, "__init__", no_server)
    args = cli.build_parser().parse_args(["decks"])
    local = cli.connect(args)
    try:
        assert isinstance(local, client.LocalClient)
    finally:
        local.close()
