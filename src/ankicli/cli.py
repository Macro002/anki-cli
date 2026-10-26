"""The ``anki-cli`` command."""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import textwrap
from typing import Any

from . import __version__
from .errors import ApiError

DEFAULT_URL = "http://127.0.0.1:8765"
_OPENED: list = []  # in-process clients to close on exit


# -- output helpers ------------------------------------------------------------------------------

def emit(value: Any, args: argparse.Namespace, human=None) -> None:
    if args.json or human is None:
        print(json.dumps(value, ensure_ascii=False, indent=2))
    else:
        human(value)


def table(rows: list[list[Any]], headers: list[str]) -> None:
    widths = [len(h) for h in headers]
    for row in rows:
        widths = [max(w, len(str(c))) for w, c in zip(widths, row)]
    print("  ".join(h.ljust(w) for h, w in zip(headers, widths)).rstrip())
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print("  ".join(str(c).ljust(w) for c, w in zip(row, widths)).rstrip())


def plain(html: str) -> str:
    """HTML to readable terminal text."""
    import re
    from html import unescape
    text = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
    text = re.sub(r"(?i)<br\s*/?>|</(div|p|li|tr|h\d)>", "\n", text)
    text = re.sub(r"(?i)<hr[^>]*>", "\n" + "─" * 30 + "\n", text)
    text = re.sub(r"\[anki:play:[qa]:\d+\]", "🔊", text)
    text = re.sub(r"\[sound:([^\]]+)\]", r"🔊 \1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text).replace("\u2068", "").replace("\u2069", "")
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def parse_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def key_values(items: list[str]) -> dict:
    out: dict[str, Any] = {}
    for item in items:
        if "=" not in item:
            raise SystemExit(f"expected key=value, got {item!r}")
        key, value = item.split("=", 1)
        out[key] = parse_value(value)
    return out


# -- connection ----------------------------------------------------------------------------------

def connect(args: argparse.Namespace):
    from .client import Client, LocalClient
    if args.url:
        return Client(args.url, key=args.key, profile=args.profile)
    if not (args.base or args.collection):
        remote = Client(os.environ.get("ANKICLI_URL", DEFAULT_URL), key=args.key, profile=args.profile, timeout=3)
        try:
            if remote.health():
                info = remote.call("server.info")
                if info.get("name") == "anki-cli":
                    remote.timeout = 300
                    remote.close()
                    return remote
        except Exception:  # noqa: BLE001 - fall back to direct access
            pass
    client = LocalClient(args.base, args.collection, args.profile)
    _OPENED.append(client)
    return client


# -- commands ------------------------------------------------------------------------------------

def cmd_serve(args: argparse.Namespace) -> int:
    from .app import App
    from .host import HostOptions
    from .profiles import Profiles
    from .server import serve
    logging.basicConfig(level=getattr(logging, args.log_level.upper()), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    profiles = Profiles(args.base, collection=args.collection,
                        options=HostOptions(backup_minutes=args.backup_minutes, idle_close_seconds=args.idle_close))
    origins = args.cors or ["http://localhost"]
    key = args.key or os.environ.get("ANKICLI_API_KEY") or None
    app = App(profiles, api_key=key, allow_exit=args.allow_exit, cors_origins=origins)
    if args.host not in ("127.0.0.1", "localhost", "::1") and not key:
        logging.warning("listening on %s without an API key: anyone who can reach this port can edit your "
                        "collection. Use --key.", args.host)
    if args.preload:
        for name in profiles.names():
            profiles.host(name).run(lambda col: None)
    serve(app, args.host, args.port)
    return 0


def cmd_call(args: argparse.Namespace) -> int:
    client = connect(args)
    if args.params and args.params.strip().startswith("{"):
        params = json.loads(args.params)
    else:
        params = key_values(([args.params] if args.params else []) + args.kv)
    result = client.legacy(args.method, **params) if args.legacy else client.call(args.method, **params)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_decks(args: argparse.Namespace) -> int:
    client = connect(args)
    tree = client.call("decks.tree")

    def human(value: dict) -> None:
        rows = []

        def walk(nodes: list, depth: int) -> None:
            for node in nodes:
                rows.append(["  " * depth + node["shortName"], node["new"], node["learning"], node["review"],
                             node["total"]])
                walk(node["children"], depth + 1)
        walk(value["children"], 0)
        table(rows, ["Deck", "New", "Learn", "Due", "Cards"])
    emit(tree, args, human)
    return 0


def cmd_deck(args: argparse.Namespace) -> int:
    client = connect(args)
    if args.action == "create":
        result = client.call("decks.create", name=args.name)
    elif args.action == "rename":
        result = client.call("decks.update", deck={"name": args.name}, name=args.new_name)
    elif args.action == "delete":
        if not args.yes:
            raise SystemExit("deleting a deck deletes its cards; add --yes to confirm")
        result = client.call("decks.delete", decks=[{"name": args.name}], deleteCards=True)
    else:
        result = client.call("decks.getCounts", deck={"name": args.name})
    emit(result, args)
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    client = connect(args)
    fields = {}
    for item in args.fields:
        if "=" not in item:
            raise SystemExit(f"fields are Field=value, got {item!r}")
        key, value = item.split("=", 1)
        fields[key] = value
    if not fields:
        raise SystemExit("give at least one Field=value")
    result = client.call("notes.create", noteType={"name": args.type}, deck={"name": args.deck}, fields=fields,
                         tags=args.tag or [], duplicates={"allow": args.allow_duplicate})
    emit(result, args, lambda r: print(f"Added note {r['noteId']} ({len(r['cardIds'])} card(s))"))
    return 0


def cmd_find(args: argparse.Namespace) -> int:
    client = connect(args)
    kind = "cards" if args.cards else "notes"
    page = client.call(f"{kind}.search", query=args.query, limit=min(args.limit, 1000))
    ids = page["ids"]
    if args.json or args.ids:
        emit(ids, args) if args.json else print("\n".join(ids))
        return 0
    if not ids:
        print("No matches.")
        return 0
    if kind == "notes":
        records = client.call("notes.getMany", ids=ids)["items"]
        rows = []
        for item in records:
            note = item.get("result")
            if note:
                first = plain(next(iter(note["fields"].values()), ""))[:50]
                rows.append([note["id"], note["noteType"]["name"], first.replace("\n", " "), " ".join(note["tags"])[:30]])
        table(rows, ["Note", "Type", "Sort field", "Tags"])
    else:
        records = client.call("cards.getMany", ids=ids)["items"]
        rows = [[c["result"]["id"], c["result"]["deck"]["name"], c["result"]["scheduling"]["queue"],
                 c["result"]["scheduling"]["intervalDays"]] for c in records if c.get("result")]
        table(rows, ["Card", "Deck", "Queue", "Interval"])
    if page["nextCursor"]:
        print(f"… more results; raise --limit (max 1000) or narrow the search.")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    client = connect(args)
    note = client.call("notes.get", id=args.id)

    def human(n: dict) -> None:
        print(f"Note {n['id']} · {n['noteType']['name']} · tags: {' '.join(n['tags']) or '—'}")
        for name, value in n["fields"].items():
            print(f"\n{name}:\n" + textwrap.indent(plain(value) or "—", "  "))
    emit(note, args, human)
    return 0


def ask(prompt: str) -> str:
    """input() that treats end of input (Ctrl-D, a closed pipe) as quitting."""
    try:
        return input(prompt).strip().lower()
    except EOFError:
        return "q"


def cmd_study(args: argparse.Namespace) -> int:
    client = connect(args)
    state = client.call("reviewer.start", **({"deck": {"name": args.deck}} if args.deck else {}))
    width = min(shutil.get_terminal_size((80, 20)).columns, 100)
    reviewed = 0
    while state["active"]:
        counts = client.call("scheduling.getQueue")
        card = state["card"]
        print("\n" + "═" * width)
        print(f"{card['deck']['name']}   new {counts['newCount']} · learn {counts['learningCount']} · "
              f"due {counts['reviewCount']}")
        print("═" * width + "\n")
        print(plain(state["rendered"]["questionHtml"]) or "(empty question)")
        command = ask("\n[Enter] show answer · [u]ndo · [q]uit > ")
        if command == "q":
            print(f"\nReviewed {reviewed} card(s).")
            return 0
        if command == "u":
            try:
                client.call("reviewer.undo")
            except ApiError as error:
                print(f"  {error}")
            state = client.call("reviewer.get")
            continue
        client.call("reviewer.showAnswer", stateToken=state["stateToken"])
        state = client.call("reviewer.get")
        answer = plain(state["rendered"]["answerHtml"])
        print("\n" + "─" * width + "\n" + answer)
        labels = [f"{i}:{a['rating'].capitalize()} ({plain(a['label'])})" for i, a in enumerate(state["answers"], 1)]
        while True:
            choice = ask("\n" + "  ".join(labels) + "  [q]uit > ")
            if choice in ("1", "2", "3", "4", ""):
                rating = ("again", "hard", "good", "easy")[int(choice or 3) - 1]
                client.call("reviewer.answer", stateToken=state["stateToken"], rating=rating)
                reviewed += 1
                break
            if choice == "q":
                print(f"\nReviewed {reviewed} card(s).")
                return 0
        state = client.call("reviewer.get")
    print(f"\nCongratulations! You have finished this deck for now. Reviewed {reviewed} card(s).")
    return 0


def cmd_tui(args: argparse.Namespace) -> int:
    try:
        from .tui.app import run
    except ImportError:
        print("The terminal app needs Textual: pip install 'ankicli[tui]'", file=sys.stderr)
        return 1
    client = connect(args)
    run(client, remote=not hasattr(client, "app"), splash=not args.no_splash)
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    client = connect(args)
    path = os.path.abspath(args.file)
    lower = path.lower()
    if lower.endswith((".csv", ".tsv", ".txt")):
        params: dict[str, Any] = {"path": path}
        if args.deck:
            params["deck"] = {"name": args.deck}
        if args.type:
            params["noteType"] = {"name": args.type}
        result = client.call("packages.importCsv", **params)
    elif lower.endswith(".colpkg"):
        if not args.yes:
            raise SystemExit("a .colpkg replaces the whole collection (a backup is made first); add --yes")
        result = client.call("collection.restore", path=path, confirm=True)
    else:
        result = client.call("packages.importAnki", path=path)
    emit(result, args, lambda r: print("Imported." + (f" New notes: {r['log']['new']}, updated: "
                                                     f"{r['log']['updated']}" if r.get("log") else "")))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    client = connect(args)
    path = os.path.abspath(args.out)
    if path.lower().endswith(".colpkg"):
        result = client.call("collection.exportPackage", path=path, includeMedia=not args.no_media)
    elif path.lower().endswith((".csv", ".tsv", ".txt")):
        result = client.call("packages.exportCsv", path=path, search=f'deck:"{args.deck}"' if args.deck else "")
    else:
        if not args.deck:
            raise SystemExit("--deck is required for .apkg exports (or export a .colpkg)")
        result = client.call("packages.export", deck={"name": args.deck}, path=path,
                             includeScheduling=args.scheduling)
    emit(result, args, lambda r: print(f"Wrote {r['path']}"))
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    client = connect(args)
    if args.action == "login":
        import getpass
        username = args.username or input("AnkiWeb email: ")
        password = os.environ.get("ANKICLI_SYNC_PASSWORD") or getpass.getpass("Password: ")
        params = {"username": username, "password": password}
        if args.endpoint:
            params["endpoint"] = args.endpoint
        emit(client.call("sync.login", **params), args, lambda r: print(f"Logged in as {r['username']}."))
        return 0
    if args.action == "logout":
        client.call("sync.logout")
        print("Logged out.")
        return 0
    if args.action == "status":
        account = client.call("sync.account")
        if account["loggedIn"]:
            account["server"] = client.call("sync.status")
        emit(account, args)
        return 0
    mode = "upload" if args.upload else "download" if args.download else "auto"
    result = client.call("sync.run", mode=mode)

    def human(r: dict) -> None:
        if r.get("fullSync") == "either":
            print("A full sync is required: the collection changed in a way that can't be merged.\n"
                  "Run `anki-cli sync --upload` to keep this collection, or `--download` to keep AnkiWeb's.")
        else:
            print({"synced": "Synced.", "uploaded": "Uploaded (full sync).",
                   "downloaded": "Downloaded (full sync)."}.get(r["outcome"], "Synced."))
            if r.get("serverMessage"):
                print(r["serverMessage"])
            if r.get("mediaError"):
                print(f"Media sync failed: {r['mediaError']}")
    emit(result, args, human)
    return 1 if result.get("fullSync") == "either" else 0


def cmd_stats(args: argparse.Namespace) -> int:
    client = connect(args)
    params = {"deck": {"name": args.deck}} if args.deck else {}
    summary = client.call("statistics.getSummary", **params)
    today = client.call("statistics.getToday")

    def human(_: Any) -> None:
        print(f"Today: {today['count']} review(s)   (next day starts {today['nextDayAt']})")
        table([[summary["cardCount"], summary["noteCount"], summary["newCount"], summary["learningCount"],
                summary["reviewCardCount"], summary["suspendedCount"], summary["reviewCount"]]],
              ["Cards", "Notes", "New", "Learning", "Review", "Suspended", "Reviews (all time)"])
    emit({"today": today, "summary": summary}, args, human)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    client = connect(args)
    result = client.call("collection.checkIntegrity")
    emit(result, args, lambda r: print("\n".join(r["problems"]) or "No problems found."))
    if args.media:
        media = client.call("media.check")
        emit(media, args, lambda m: print(f"Media: {len(m['unused'])} unused, {len(m['missing'])} missing file(s)."))
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    client = connect(args)
    if args.list:
        emit(client.call("collection.backups"), args,
             lambda b: table([[x["createdAt"], x["size"], x["path"]] for x in b], ["Created", "Bytes", "Path"]))
        return 0
    emit(client.call("collection.backup"), args, lambda r: print(f"Backup: {r['path']}"))
    return 0


def cmd_profiles(args: argparse.Namespace) -> int:
    client = connect(args)
    if args.action == "create":
        client.call("profiles.create", name=args.name)
    elif args.action == "rename":
        client.call("profiles.rename", name=args.name, newName=args.new_name)
    elif args.action == "delete":
        if not args.yes:
            raise SystemExit("this deletes the profile's collection and media; add --yes")
        client.call("profiles.delete", name=args.name, confirm=True)
    elif args.action == "switch":
        client.call("profiles.switch", name=args.name)
    active = (client.call("profiles.getActive") or {}).get("name")
    names = [p["name"] for p in client.call("profiles.list")]
    emit({"active": active, "profiles": names}, args,
         lambda _: print("\n".join(("* " if n == active else "  ") + n for n in names)))
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    client = connect(args)
    emit(client.call("collection.info"), args)
    return 0


# -- parser --------------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="anki-cli", description="Anki's own engine as a headless server and command-line tool.",
        epilog="Run `anki-cli serve` for an AnkiConnect-compatible server on port 8765.")
    parser.add_argument("--version", action="version", version=f"anki-cli {__version__}")

    def options(target: argparse.ArgumentParser, suppress: bool) -> None:
        # Accepted before and after the command; the copy on each command must not
        # overwrite a value given before it, hence SUPPRESS defaults there.
        default = argparse.SUPPRESS if suppress else None
        group = target.add_argument_group("collection")
        group.add_argument("--base", default=default,
                           help="profiles folder (default: $ANKICLI_BASE or ~/.local/share/anki-cli)")
        group.add_argument("--collection", default=default,
                           help="a single collection.anki2 file instead of a profiles folder")
        group.add_argument("--profile", default=default, help="profile to use (default: the active profile)")
        group.add_argument("--url", default=default, help="talk to a running server instead of opening the collection")
        group.add_argument("--key", default=default, help="API key of the server")
        target.add_argument("--json", action="store_true", default=argparse.SUPPRESS if suppress else False,
                            help="print raw JSON")

    options(parser, suppress=False)
    common = argparse.ArgumentParser(add_help=False)
    options(common, suppress=True)
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    def add(name: str, func, help_text: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, parents=[common], help=help_text, description=help_text)
        p.set_defaults(func=func)
        return p

    p = add("serve", cmd_serve, "Run the server (Anki-Connect legacy + v1 + extensions).")
    p.add_argument("--host", default=os.environ.get("ANKICLI_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.environ.get("ANKICLI_PORT", 8765)))
    p.add_argument("--cors", action="append", metavar="ORIGIN", help="allowed browser origin (repeatable, * for any)")
    p.add_argument("--allow-exit", action="store_true", help="allow guiExitAnki/application.exit to stop the server")
    p.add_argument("--backup-minutes", type=int, default=30, help="minutes between automatic backups (0: off)")
    p.add_argument("--idle-close", type=int, default=0, help="close collections idle this many seconds (0: never)")
    p.add_argument("--preload", action="store_true", help="open every profile at startup")
    p.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])

    p = add("call", cmd_call, "Call any API method: anki-cli call decks.list, anki-cli call notes.search query=cat")
    p.add_argument("method")
    p.add_argument("params", nargs="?", help="JSON object, or the first key=value")
    p.add_argument("kv", nargs="*", help="more key=value pairs (values are parsed as JSON when possible)")
    p.add_argument("--legacy", action="store_true", help="call a legacy Anki-Connect action instead")

    add("decks", cmd_decks, "Show the deck tree with due counts.")
    p = add("deck", cmd_deck, "Create, rename, delete or inspect a deck.")
    p.add_argument("action", choices=["create", "rename", "delete", "counts"])
    p.add_argument("name")
    p.add_argument("new_name", nargs="?")
    p.add_argument("--yes", action="store_true")

    p = add("add", cmd_add, "Add a note: anki-cli add --deck French Front=chat Back=cat")
    p.add_argument("--deck", default="Default")
    p.add_argument("--type", default="Basic", help="note type (default: Basic)")
    p.add_argument("--tag", action="append")
    p.add_argument("--allow-duplicate", action="store_true")
    p.add_argument("fields", nargs="+", metavar="Field=value")

    p = add("find", cmd_find, "Search notes (or cards) with Anki's search syntax.")
    p.add_argument("query")
    p.add_argument("--cards", action="store_true")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--ids", action="store_true", help="print only IDs")

    p = add("show", cmd_show, "Show a note.")
    p.add_argument("id")

    p = add("study", cmd_study, "Study in the terminal with Anki's scheduler.")
    p.add_argument("deck", nargs="?")

    p = add("tui", cmd_tui, "The full-screen terminal app: decks, reviewer, browser, editor, stats, sync.")
    p.add_argument("--no-splash", action="store_true", help="skip the logo at startup")

    p = add("import", cmd_import, "Import .apkg, .colpkg, .csv/.tsv/.txt.")
    p.add_argument("file")
    p.add_argument("--deck")
    p.add_argument("--type")
    p.add_argument("--yes", action="store_true")

    p = add("export", cmd_export, "Export a deck (.apkg), notes (.csv) or the collection (.colpkg).")
    p.add_argument("out")
    p.add_argument("--deck")
    p.add_argument("--scheduling", action="store_true", help="include scheduling in .apkg")
    p.add_argument("--no-media", action="store_true")

    p = add("sync", cmd_sync, "Sync with AnkiWeb or a self-hosted server.")
    p.add_argument("action", nargs="?", choices=["run", "login", "logout", "status"], default="run")
    p.add_argument("--username")
    p.add_argument("--endpoint", help="self-hosted sync server URL")
    p.add_argument("--upload", action="store_true", help="full sync: replace the server's copy")
    p.add_argument("--download", action="store_true", help="full sync: replace this collection")

    p = add("stats", cmd_stats, "Today's reviews and collection counts.")
    p.add_argument("--deck")
    p = add("check", cmd_check, "Check (and repair) the database.")
    p.add_argument("--media", action="store_true", help="also check media")
    p = add("backup", cmd_backup, "Create a backup now (or --list them).")
    p.add_argument("--list", action="store_true")
    p = add("profiles", cmd_profiles, "List, create, rename, delete or switch profiles.")
    p.add_argument("action", nargs="?", choices=["list", "create", "rename", "delete", "switch"], default="list")
    p.add_argument("name", nargs="?")
    p.add_argument("new_name", nargs="?")
    p.add_argument("--yes", action="store_true")
    add("info", cmd_info, "Collection paths and counts.")
    return parser


def main(argv: list[str] | None = None) -> int:
    # Consoles with a legacy code page (e.g. Windows cp1252) can't print every card
    # character; replace those instead of crashing.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args) or 0
    except ApiError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print()
        return 130
    finally:
        while _OPENED:
            _OPENED.pop().close()


if __name__ == "__main__":
    sys.exit(main())
