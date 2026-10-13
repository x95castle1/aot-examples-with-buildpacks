import os
from pathlib import Path
import shutil
import sys


def format_table(rows):
    """Render open tables with aligned values and optional terminal colors."""
    widths = [max(len(row[column]) for row in rows) for column in range(len(rows[0]))]
    force_color = os.environ.get("FORCE_COLOR")
    interactive = sys.stdout.isatty()
    color = interactive and os.environ.get("TERM") != "dumb"
    if force_color is not None:
        color = force_color not in ("", "0")
    if os.environ.get("NO_COLOR"):
        color = False

    def paint(value, style):
        return f"\033[{style}m{value}\033[0m" if color else value

    def render(columns):
        def format_row(row):
            return "   ".join(row[column].ljust(widths[column]) if column == 0
                              else row[column].rjust(widths[column]) for column in columns)

        separator = paint("   ".join("─" * widths[column] for column in columns), "38;2;65;71;77")
        lines = [paint(format_row(rows[0]), "1;38;2;255;221;161"), separator]
        for index, row in enumerate(rows[1:]):
            lines.append(paint(format_row(row), "38;2;216;217;219"))
            if index < len(rows) - 2:
                lines.append(separator)
        return "\n".join(lines)

    # Repeat the row label when detailed tables need multiple groups to fit the terminal.
    groups, columns = [], [0]
    available = shutil.get_terminal_size(fallback=(120, 24)).columns if interactive else None
    for column in range(1, len(widths)):
        if available and len(columns) > 1 and sum(widths[i] for i in columns) + widths[column] + 3 * len(columns) > available:
            groups.append(columns)
            columns = [0]
        columns.append(column)
    groups.append(columns)
    return "\n\n".join(render(columns) for columns in groups)


def report_link(path):
    """Link container reports to the corresponding file on the host."""
    path = Path(path).absolute()
    host_results = os.environ.get("REPORT_HOST_RESULTS")
    if host_results and path.is_relative_to("/results"):
        path = Path(host_results) / path.relative_to("/results")
    uri = path.as_uri()
    if sys.stdout.isatty() and os.environ.get("TERM") != "dumb":
        return f"\033]8;;{uri}\033\\{uri}\033]8;;\033\\"
    return uri


