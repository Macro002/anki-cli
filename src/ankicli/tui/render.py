"""Terminal rendering: the logo, and card HTML as Rich text."""
from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser

from rich.text import Text

ACCENT = "#2b8cff"
LOGO = """\
                                                                                                ▒▒▒▒▒▒▒▒▒▒▒
                                                                                           ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒
    ██████                                                              ░░░░░░        ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒
  ██████████                                                          ░░░░░░░░░░░░░░░░░░░░░░░░▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒
  ████████████                                                  ▒▒▒▒▒▒▒▒▒▒░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░▒
  ██████████████                                              ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒░░░░░░░░░░░░░░░░░░░░░░░░░░
   ███████████████                                            ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒░░░░░░░░░░░░░░
     ███████████████                                         ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒░░░░░░░░░░
       ███████████████                                       ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒░░░░░░░░▒░
         ███████████████                                    ░▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒░░░░░░░▒▒
           ███████████████                                  ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒██▓▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒░░░░░░░░▒▒▒
              ██████████████                                ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒████▓▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒░░░░░░░░▒▒▒▒
                ██████████████                              ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒██████▓▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒░░░░░░░░▒▒▒▒░
                ██████████████                             ░▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒████████▓▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒░░░░░░░░▒▒▒▒▒▒░
              ███████████████                              ▒▒▒▒▒▒▒▒▒▓█████████████████████████▒▒▒▒▒▒░░░░░░░░░░░▒▒▒▒▒▒░
            ███████████████                                ▒▒▒▒▒▒▒▒▒▒▒▓█████████████████████▒▒▒▒▒▒░░░░░░░░░░░░░▒▒▒▒▒▒▒░
          ███████████████                                 ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒████████████████▓▒▒▒▒▒░░░░░░░░░░░░░░░░▒▒▒▒▒▒▒░
        ███████████████                                   ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▓█████████████▒▒▒▒░░░░░░░░░░░░░░░░░░▒▒▒▒▒▒▒░
      ███████████████                                     ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒██████████████▓░░░░░░░░░░░░░░░░░░░░░▒▒▒▒▒░░
    ██████████████       ██████████████████████           ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▓███████████████▒░░░░░░░░░░░░░░░░░░░░▒░
  ██████████████      ████████████████████████████       ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒█████▒▒▒▒▒▒▓████▒░░░░░░░░░░░░░░░░░░░░
  ████████████        ██████████████████████████████     ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒██▒▒▒▒▒▒▒░░░░░▓█▒░░░░░░░░░░░░░░░░░░░░
  ███████████         ██████████████████████████████    ░▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
    ██████            ████████████████████████████      ░▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
                                                         ░▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
                                                           ░▒▒▒▒▒▒▒▒▒▒░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
                                                                    ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
                                                                                ░░░░░░░░░░░░░░░░░░░░
                                                                                             ░░░
"""

# Logo palette: the prompt and the star are white, the cards three shades of blue.
LOGO_COLORS = {"█": "#f5f7ff", "▓": "#a9ccff", "▒": "#2b8cff", "░": "#0b4ec4"}


def logo_lines() -> list[str]:
    lines = LOGO.split("\n")
    indent = min(len(line) - len(line.lstrip()) for line in lines if line.strip())
    return [line[indent:].rstrip() for line in lines]


def scaled_logo(step_x: int = 2, step_y: int = 2) -> list[str]:
    """A smaller logo: each output cell takes the strongest glyph of its block."""
    lines = logo_lines()
    width = max(len(line) for line in lines)
    grid = [line.ljust(width) for line in lines]
    rank = {" ": 0, "░": 1, "▒": 2, "▓": 3, "█": 4}
    out = []
    for y in range(0, len(grid), step_y):
        row = []
        for x in range(0, width, step_x):
            block = [grid[yy][xx] for yy in range(y, min(y + step_y, len(grid)))
                     for xx in range(x, min(x + step_x, width))]
            filled = [c for c in block if c != " "]
            if len(filled) * 2 < len(block):
                row.append(" ")
            else:
                row.append(max(filled, key=lambda c: rank[c]) if "█" in filled and filled.count("█") * 2 >= len(filled)
                           else max(set(filled), key=filled.count))
        out.append("".join(row).rstrip())
    while out and not out[-1].strip():
        out.pop()
    return out


def logo_text(lines: list[str]) -> Text:
    """Shades become solid colored blocks: crisper than ░▒▓ in most terminal fonts."""
    text = Text(no_wrap=True, overflow="crop")
    for index, line in enumerate(lines):
        for char in line:
            text.append("█" if char in LOGO_COLORS else char, style=LOGO_COLORS.get(char, ""))
        if index < len(lines) - 1:
            text.append("\n")
    return text


# -- card HTML -----------------------------------------------------------------------------------

BLOCK = {"div", "p", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "table", "blockquote", "section"}
SKIP = {"script", "style", "head", "title"}
STYLE_TAGS = {"b": "bold", "strong": "bold", "i": "italic", "em": "italic", "u": "underline",
              "s": "strike", "del": "strike", "strike": "strike", "code": "bold #9cc8ff", "sup": "dim", "sub": "dim",
              "h1": "bold", "h2": "bold", "h3": "bold"}


class _CardParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text = Text()
        self.styles: list[tuple[str, str]] = []
        self.skip = 0
        self.ruby: list[str] = []

    def newline(self) -> None:
        if self.text.plain and not self.text.plain.endswith("\n"):
            self.text.append("\n")

    def current(self) -> str:
        return " ".join(style for _, style in self.styles)

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = dict(attrs)
        if tag in SKIP:
            self.skip += 1
            return
        if tag in BLOCK:
            self.newline()
        if tag == "br":
            self.text.append("\n")
        elif tag == "hr":
            self.newline()
            self.text.append("─" * 30 + "\n", style="#3b4252")
        elif tag == "img":
            name = attributes.get("src") or "image"
            self.text.append(f"[image: {name}]", style="italic #8a93a6")
        elif tag == "input":
            self.text.append("[ type your answer ]", style="italic #8a93a6")
        elif tag == "rt":
            self.ruby.append(len(self.text.plain))
            self.text.append("(", style="#8a93a6")
            self.styles.append((tag, "#8a93a6"))
        elif tag in STYLE_TAGS:
            self.styles.append((tag, STYLE_TAGS[tag]))
        elif tag == "span" and "cloze" in (attributes.get("class") or ""):
            self.styles.append((tag, f"bold {ACCENT}"))
        elif tag in ("span", "font", "a", "ruby", "rb"):
            self.styles.append((tag, ""))

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP:
            self.skip = max(0, self.skip - 1)
            return
        for index in range(len(self.styles) - 1, -1, -1):
            if self.styles[index][0] == tag:
                del self.styles[index]
                break
        if tag == "rt":
            self.text.append(")", style="#8a93a6")
        if tag in BLOCK:
            self.newline()

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        data = re.sub(r"[ \t\r\n]+", " ", data)
        if not data.strip() and (not self.text.plain or self.text.plain.endswith("\n")):
            return
        self.text.append(data, style=self.current() or None)


def card_text(html: str) -> Text:
    """Card HTML as Rich text: styles, cloze, ruby, images and audio markers."""
    html = re.sub(r"\[anki:play:[qa]:\d+\]", "🔊 ", html)
    html = re.sub(r"\[sound:([^\]]+)\]", r"🔊 \1 ", html)
    html = re.sub(r"\[\[type:[^\]]+\]\]", "<input>", html)
    parser = _CardParser()
    parser.feed(html)
    parser.close()
    text = parser.text
    plain = text.plain
    # Trim blank lines at the edges and collapse runs of empty lines.
    start = len(plain) - len(plain.lstrip("\n "))
    end = len(plain.rstrip("\n "))
    text = text[start:end]
    while "\n\n\n" in text.plain:
        index = text.plain.index("\n\n\n")
        text = text[:index] + text[index + 1:]
    return text


def plain(html: str) -> str:
    """HTML to one line of text (tables, previews)."""
    text = re.sub(r"(?is)<(script|style).*?</\1>", "", html or "")
    text = re.sub(r"(?i)<br\s*/?>|</(div|p|li)>", " ", text)
    text = re.sub(r"\[sound:[^\]]+\]", "🔊", text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def label(text: str) -> str:
    """Interval labels without Anki's invisible bidi marks."""
    return text.replace("\u2068", "").replace("\u2069", "")
