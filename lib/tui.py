"""Terminal output blocks using rich panels."""

from pathlib import Path
from typing import Literal

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

BlockType = Literal["AGENT", "PROMPT", "THINKING", "RESPONSE", "INFO", "ERROR"]

BLOCK_COLORS = {
    "AGENT": "bright_yellow",
    "PROMPT": "bright_red",
    "THINKING": "bright_magenta",
    "RESPONSE": "bright_cyan",
    "INFO": "yellow",
    "ERROR": "bright_red",
}

# Module-level log console — set via setup_log() before any output.
_log_console: Console | None = None


def setup_log(path: Path) -> None:
    """Open a log file for all block output."""
    global _log_console
    _log_console = Console(file=open(path, "w", encoding="utf-8"), width=120)


def close_log() -> None:
    """Close the log file if open."""
    global _log_console
    if _log_console and hasattr(_log_console.file, "close"):
        _log_console.file.close()  # type: ignore[union-attr]
    _log_console = None


class TerminalBlock:
    """A content block rendered as a rich Panel."""

    def __init__(
        self,
        block_type: BlockType,
        content: str,
        subtitle: str = "",
        max_lines: int = 20,
        title_prefix: str = "",
    ):
        self.block_type = block_type
        self.content = content
        self.subtitle = subtitle
        self.max_lines = max_lines
        self.title_prefix = title_prefix

    def _title(self) -> str:
        if self.title_prefix:
            return f"{self.title_prefix} - {self.block_type}"
        return self.block_type

    def render(self, full: bool = False) -> Panel:
        lines = self.content.split("\n")
        total = len(lines)
        color = BLOCK_COLORS.get(self.block_type, "white")
        title = self._title()

        if full or total <= self.max_lines:
            body = Text("\n".join(lines))
        else:
            shown = "\n".join(lines[: self.max_lines])
            hidden = total - self.max_lines
            body = Text(f"{shown}\n\n  [-{hidden} more lines hidden-]")

        return Panel(
            body,
            title=f"[bold {color}]{title}[/bold {color}]",
            title_align="left",
            subtitle=self.subtitle or None,
            subtitle_align="left",
            border_style=color,
            padding=(0, 1),
        )

    def write_to_log(self) -> None:
        """Write this block to the log console if one is configured."""
        if _log_console:
            _log_console.print(self.render(full=True))


def print_block(block: TerminalBlock) -> None:
    """Print a block to the terminal and log file."""
    console = Console()
    console.print(block.render())
    block.write_to_log()
