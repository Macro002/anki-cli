"""Generate docs/methods.md from the method registry (python tools/gen_methods_doc.py)."""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ankicli import legacy, params  # noqa: E402
from ankicli.methods import METHODS  # noqa: E402
from ankicli.services import Services  # noqa: E402


def properties(validator) -> dict | None:
    for cell in validator.__closure__ or ():
        value = cell.cell_contents
        if isinstance(value, dict) and all(isinstance(v, tuple) and len(v) == 2 for v in value.values()):
            return value
    return None


def describe(validator) -> str:
    props = properties(validator)
    if props is None:
        return ""
    parts = []
    for name, (_, default) in props.items():
        if name == "session":
            continue
        if default is params.MISSING:
            parts.append(f"`{name}`")
        elif default is params.OPTIONAL:
            parts.append(f"`{name}?`")
        else:
            shown = default() if callable(default) else default
            parts.append(f"`{name}={shown!r}`".replace("'", '"'))
    return ", ".join(parts)


def summary(name: str) -> str:
    method = METHODS[name]
    if method.summary:
        return method.summary
    handler = getattr(Services, name.replace(".", "_"), None)
    doc = inspect.getdoc(handler) if handler else None
    return (doc or "").split("\n\n")[0].replace("\n", " ")


def table(names: list[str]) -> list[str]:
    lines = ["| Method | Parameters | Kind | Notes |", "|---|---|---|---|"]
    for name in names:
        method = METHODS[name]
        kind = method.effect + (" · operation" if method.completion == "operation" else "")
        lines.append(f"| `{name}` | {describe(method.validate)} | {kind} | {summary(name)} |")
    return lines


def main() -> None:
    core = sorted(name for name, method in METHODS.items() if not method.extension)
    extra = sorted(name for name, method in METHODS.items() if method.extension)
    out = ["# Method reference", "",
           "Generated from the registry by `tools/gen_methods_doc.py`. `name?` is optional; `name=value` shows "
           "the default. Every collection method also accepts an optional `session`.", "",
           f"## API v1 (Anki-Connect compatible) — {len(core)} methods", "",
           "Same names, parameters, results and error codes as Anki-Connect's "
           "[API v1](https://git.sr.ht/~foosoft/anki-connect/tree/master/item/API_V1.md). "
           "*Operation* methods return a handle; anki-cli completes them before replying, so "
           "`operations.get` returns the final result at once.", "", *table(core), "",
           f"## anki-cli extensions — {len(extra)} methods", "",
           "Same conventions as v1 (references, string IDs, `{\"items\": [...]}` for bulk results).", "",
           *table(extra), "",
           f"## Legacy actions — {len(legacy.ACTIONS)}", "",
           "All Anki-Connect legacy actions at `POST /` with `action`/`version`/`params`:", ""]
    out.append(", ".join(f"`{name}`" for name in sorted(legacy.ACTIONS)))
    target = Path(__file__).resolve().parents[1] / "docs" / "methods.md"
    target.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {target} ({len(core)} v1, {len(extra)} extensions, {len(legacy.ACTIONS)} legacy)")


if __name__ == "__main__":
    main()
