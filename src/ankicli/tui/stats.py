"""Statistics: today, card counts, a review heatmap and the due forecast."""
from __future__ import annotations

import datetime as dt

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Static

HEAT = ["#1b2433", "#0b3a8c", "#0b4ec4", "#1a72f5", "#5aa2ff"]
BARS = " ▁▂▃▄▅▆▇█"
STATES = [("newCards", "New", "#5aa2ff"), ("learn", "Learning", "#ff7b72"), ("relearn", "Relearning", "#e6a23c"),
          ("young", "Young", "#3fb950"), ("mature", "Mature", "#238636"), ("suspended", "Suspended", "#a39a6b"),
          ("buried", "Buried", "#7d8590")]


def duration(ms: int) -> str:
    seconds = ms // 1000
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    return f"{minutes}m" if minutes < 60 else f"{minutes // 60}h {minutes % 60:02d}m"


def heatmap(counts: dict[int, int], weeks: int) -> Text:
    """GitHub-style: a column per week, Monday at the top; counts keyed by day offset (0 = today)."""
    today = dt.date.today()
    start = today - dt.timedelta(days=today.weekday() + 7 * (weeks - 1))
    peak = max(counts.values(), default=0)

    def level(value: int) -> int:
        if value <= 0 or peak <= 0:
            return 0
        return min(4, 1 + int(3 * value / peak))

    text = Text()
    months = Text("    ")
    last, skip = None, False
    for week in range(weeks):
        month = (start + dt.timedelta(weeks=week)).strftime("%b")
        if skip:
            skip = False
        elif month != last and week < weeks - 1:
            months.append(f"{month} ", style="#8a93a6")  # a label spans two weeks
            skip = True
        else:
            months.append("  ")
        last = month
    text.append_text(months)
    text.append("\n")
    for weekday in range(7):
        text.append(["Mo ", "   ", "We ", "   ", "Fr ", "   ", "Su "][weekday] + " ", style="#4b5565")
        for week in range(weeks):
            day = start + dt.timedelta(weeks=week, days=weekday)
            if day > today:
                text.append("  ")
                continue
            value = counts.get((day - today).days, 0)
            text.append("■ ", style=HEAT[level(value)])
        if weekday < 6:
            text.append("\n")
    return text


def forecast(future: dict[int, int], days: int) -> Text:
    values = [future.get(day, 0) for day in range(days)]
    peak = max(values, default=0) or 1
    rows = 4
    text = Text()
    for row in range(rows, 0, -1):
        for value in values:
            level = value / peak * rows
            if level >= row:
                char = "█"
            elif level > row - 1:
                char = BARS[max(1, round((level - (row - 1)) * 8))]
            else:
                char = " "
            text.append(char + " ", style="#2b8cff")
        text.append("\n")
    text.append("today".ljust(2 * days - 8) + f"+{days - 1}d", style="#4b5565")
    return text


class StatsScreen(Screen):
    BINDINGS = [Binding("c", "scope", "Deck / collection"), Binding("escape,q", "back", "Back")]

    def __init__(self, deck: str | None = None):
        super().__init__()
        self.deck = deck
        self.whole = deck is None

    def compose(self) -> ComposeResult:
        yield Static(id="stats-bar")
        with VerticalScroll(id="stats"):
            with Horizontal(id="stats-grid"):
                yield Static(id="stats-today", classes="panel")
                yield Static(id="stats-counts", classes="panel")
            yield Static(id="stats-heatmap", classes="panel")
            yield Static(id="stats-forecast", classes="panel")
        yield Footer()

    def on_mount(self) -> None:
        self.load()

    def on_resize(self) -> None:
        self.load()

    def action_scope(self) -> None:
        if self.deck:
            self.whole = not self.whole
            self.load()

    def load(self) -> None:
        search = "" if self.whole or not self.deck else f'"deck:{self.deck}"'
        graphs = self.app.try_api("statistics.graphs", search=search, days=365)
        if graphs is None:
            return
        scope = "Whole collection" if self.whole or not self.deck else self.deck.replace("::", " › ")
        self.query_one("#stats-bar", Static).update(Text.assemble((" ‹ esc  ", "#8a93a6"), ("Statistics", "bold"),
                                                                  ("  ·  ", "#4b5565"), (scope, "#e6e9f2"),
                                                                  ("   c switch" if self.deck else "", "#4b5565")))
        today = graphs["today"]
        correct = round(100 * today["correctCount"] / today["answerCount"]) if today["answerCount"] else None
        retention = graphs.get("trueRetention", {}).get("month", {})
        passed = retention.get("youngPassed", 0) + retention.get("maturePassed", 0)
        failed = retention.get("youngFailed", 0) + retention.get("matureFailed", 0)
        lines = Text()
        lines.append("Today\n\n", style="bold #2b8cff")
        lines.append(f"{today['answerCount']}", style="bold #e6e9f2")
        lines.append(f" cards in {duration(today['answerMillis'])}\n", style="#8a93a6")
        lines.append(f"{correct}%" if correct is not None else "—", style="bold #e6e9f2")
        lines.append(" correct\n", style="#8a93a6")
        lines.append(f"learn {today['learnCount']} · review {today['reviewCount']} · "
                     f"relearn {today['relearnCount']}\n\n", style="#8a93a6")
        lines.append(f"{round(100 * passed / (passed + failed))}%" if passed + failed else "—", style="bold #e6e9f2")
        lines.append(" retention this month", style="#8a93a6")
        self.query_one("#stats-today", Static).update(lines)

        counts = graphs["cardCounts"]["includingInactive"]
        total = sum(counts.get(key, 0) for key, _, _ in STATES) or 1
        bar_width = max(10, min(48, self.size.width // 2 - 12))
        text = Text()
        text.append("Cards\n\n", style="bold #2b8cff")
        used = 0
        for index, (key, _, color) in enumerate(STATES):
            width = round(counts.get(key, 0) / total * bar_width) if index < len(STATES) - 1 else bar_width - used
            width = max(0, min(width, bar_width - used))
            used += width
            text.append("█" * width, style=color)
        text.append("\n\n")
        for key, name, color in STATES:
            if counts.get(key, 0):
                text.append("■ ", style=color)
                text.append(f"{name:<11}", style="#8a93a6")
                text.append(f"{counts[key]}\n", style="bold #e6e9f2")
        if total == 1 and not any(counts.values()):
            text.append("No cards yet.", style="#8a93a6")
        self.query_one("#stats-counts", Static).update(text)

        reviews = {int(day): sum(kinds.values()) for day, kinds in graphs["reviews"]["count"].items()}
        weeks = max(8, min(52, (self.size.width - 12) // 2))
        total_reviews = sum(value for day, value in reviews.items() if day > -7 * weeks)
        streak = 0
        while reviews.get(-streak, 0) > 0:
            streak += 1
        heat = Text()
        heat.append("Reviews", style="bold #2b8cff")
        heat.append(f"   {total_reviews} in {weeks} weeks · streak {streak} day{'s' if streak != 1 else ''}\n\n",
                    style="#8a93a6")
        heat.append_text(heatmap(reviews, weeks))
        heat.append("\n\n   less ", style="#4b5565")
        for color in HEAT:
            heat.append("■ ", style=color)
        heat.append("more", style="#4b5565")
        self.query_one("#stats-heatmap", Static).update(heat)

        future = {int(day): value for day, value in graphs["futureDue"]["futureDue"].items()}
        days = max(14, min(60, (self.size.width - 8) // 2))
        due = Text()
        due.append("Forecast", style="bold #2b8cff")
        due.append(f"   {future.get(0, 0)} due today · {sum(future.get(d, 0) for d in range(1, 8))} "
                   f"in the next 7 days · ~{graphs['futureDue'].get('dailyLoad', 0)}/day\n\n", style="#8a93a6")
        due.append_text(forecast(future, days))
        self.query_one("#stats-forecast", Static).update(due)

    def action_back(self) -> None:
        self.app.pop_screen()
