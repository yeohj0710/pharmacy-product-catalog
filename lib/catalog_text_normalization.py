from __future__ import annotations

import html
import re
import unicodedata
from html.parser import HTMLParser
from typing import Any


ZERO_WIDTH_PATTERN = re.compile(r"[\u200b-\u200f\u2060\ufeff]")
BLOCK_TAGS = {
    "address",
    "article",
    "blockquote",
    "div",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "ol",
    "p",
    "section",
    "ul",
}


def _repair_upstream_markers(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = ZERO_WIDTH_PATTERN.sub("", text).replace("\u00a0", " ").replace("\u3000", " ")

    # health.kr serializes line breaks as `brbr<P></P>`. Handle the longest
    # marker first; matching `br<P></P>` first leaves a visible trailing `br`.
    text = re.sub(r"(?i)brbr\s*<p(?:\s+[^>]*)?>\s*</p>", "\n\n", text)
    text = re.sub(r"(?i)brbr", "\n\n", text)
    text = re.sub(r"(?i)br\s*<p(?:\s+[^>]*)?>\s*</p>", "\n\n", text)
    text = re.sub(r"(?i)</?br\s*/?>", "\n", text)

    # Repair values already materialized by the old, order-dependent cleaner.
    text = re.sub(r"(?i)(?<=[가-힣0-9.!?\]\)])br(?=\s*(?:\n|$))", "\n", text)
    text = re.sub(r"(?i)(?<=[가-힣])br(?=\s*(?:\n|$))", "\n", text)
    text = re.sub(r"(?im)^\s*br\s*$", "\n", text)

    # Four cetirizine records contain upstream question marks where the source
    # table denotes either a numeric range or subtraction in the CLcr formula.
    text = re.sub(r"(?<=\d)\s*\?\s*(?=\d)", "–", text)
    text = re.sub(r"(?<=\d)\s*\?\s*(?=[가-힣A-Za-z(])", " - ", text)
    return unicodedata.normalize("NFC", text)


def _clean_lines(value: str) -> str:
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in value.splitlines()]
    output: list[str] = []
    for line in lines:
        if line:
            output.append(line)
        elif output and output[-1] != "":
            output.append("")
    return "\n".join(output).strip()


def _paragraphs(value: str) -> list[dict[str, str]]:
    text = _clean_lines(value)
    return [
        {"type": "paragraph", "text": paragraph.strip()}
        for paragraph in re.split(r"\n\s*\n", text)
        if paragraph.strip()
    ]


def _positive_span(attrs: list[tuple[str, str | None]], name: str) -> int:
    raw = next((value for key, value in attrs if key.lower() == name), None)
    try:
        return max(1, int(raw or 1))
    except ValueError:
        return 1


def _expand_table(raw_rows: list[list[dict[str, Any]]]) -> tuple[list[list[str]], list[list[bool]]]:
    occupied: dict[tuple[int, int], tuple[str, bool]] = {}
    width = 0
    for row_index, raw_row in enumerate(raw_rows):
        column = 0
        for cell in raw_row:
            while (row_index, column) in occupied:
                column += 1
            text = _clean_lines("".join(cell["parts"]))
            rowspan = cell["rowspan"]
            colspan = cell["colspan"]
            for row_offset in range(rowspan):
                for column_offset in range(colspan):
                    position = (row_index + row_offset, column + column_offset)
                    occupied[position] = (
                        text if row_offset == 0 and column_offset == 0 else "",
                        bool(cell["header"]),
                    )
            column += colspan
            width = max(width, column)
    height = max((row for row, _ in occupied), default=-1) + 1
    rows = [[occupied.get((row, column), ("", False))[0] for column in range(width)] for row in range(height)]
    header_flags = [[occupied.get((row, column), ("", False))[1] for column in range(width)] for row in range(height)]
    return rows, header_flags


def _build_table(raw_rows: list[list[dict[str, Any]]]) -> dict[str, Any] | None:
    rows, header_flags = _expand_table(raw_rows)
    if not rows:
        return None
    first = rows[0]
    source_header = bool(header_flags[0]) and all(header_flags[0][index] for index in range(len(first)) if first[index])
    inferred_header = (
        len(rows) > 1
        and any(first)
        and not any(re.search(r"\d", cell) for cell in first)
        and sum(bool(cell) for cell in first) >= 2
    )
    if source_header or inferred_header:
        return {"type": "table", "headers": first, "rows": rows[1:]}
    return {"type": "table", "headers": [], "rows": rows}


def _render_table(block: dict[str, Any]) -> str:
    lines: list[str] = []
    if block.get("headers"):
        lines.append(" | ".join(block["headers"]))
    lines.extend(" | ".join(row).rstrip(" |") for row in block.get("rows", []))
    return "\n".join(line for line in lines if line.strip())


class _RichTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[dict[str, Any]] = []
        self.text_parts: list[str] = []
        self.tables: list[dict[str, Any]] = []

    def _flush_text(self) -> None:
        self.blocks.extend(_paragraphs("".join(self.text_parts)))
        self.text_parts = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "table":
            parent_parts = self.tables[-1].get("cell", {}).get("parts") if self.tables and self.tables[-1].get("cell") else None
            if not self.tables:
                self._flush_text()
            self.tables.append({"rows": [], "row": None, "cell": None, "parent_parts": parent_parts})
            return
        if self.tables:
            table = self.tables[-1]
            if tag == "tr":
                table["row"] = []
                table["rows"].append(table["row"])
            elif tag in {"td", "th"}:
                if table["row"] is None:
                    table["row"] = []
                    table["rows"].append(table["row"])
                table["cell"] = {
                    "parts": [],
                    "header": tag == "th",
                    "rowspan": _positive_span(attrs, "rowspan"),
                    "colspan": _positive_span(attrs, "colspan"),
                }
                table["row"].append(table["cell"])
            elif tag == "br" and table.get("cell"):
                table["cell"]["parts"].append("\n")
            elif tag in BLOCK_TAGS and table.get("cell"):
                table["cell"]["parts"].append("\n")
            return
        if tag == "br":
            self.text_parts.append("\n")
        elif tag in BLOCK_TAGS:
            self.text_parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "table" and self.tables:
            table = self.tables.pop()
            block = _build_table(table["rows"])
            if block:
                if table["parent_parts"] is not None:
                    table["parent_parts"].append("\n" + _render_table(block) + "\n")
                else:
                    self.blocks.append(block)
            return
        if self.tables:
            table = self.tables[-1]
            if tag in {"td", "th"}:
                table["cell"] = None
            elif tag == "tr":
                table["row"] = None
            elif tag in BLOCK_TAGS and table.get("cell"):
                table["cell"]["parts"].append("\n")
            return
        if tag in BLOCK_TAGS:
            self.text_parts.append("\n\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() != "br":
            self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self.tables:
            cell = self.tables[-1].get("cell")
            if cell is not None:
                cell["parts"].append(data)
            return
        self.text_parts.append(data)

    def finish(self) -> list[dict[str, Any]]:
        self._flush_text()
        return self.blocks


def parse_health_rich_text(value: Any) -> dict[str, Any]:
    parser = _RichTextParser()
    parser.feed(_repair_upstream_markers(value))
    parser.close()
    blocks = parser.finish()
    rendered = [block["text"] if block["type"] == "paragraph" else _render_table(block) for block in blocks]
    return {"text": "\n\n".join(text for text in rendered if text).strip(), "blocks": blocks}


def normalize_health_text(value: Any) -> str:
    return parse_health_rich_text(value)["text"]


def clean_ingredient(value: Any) -> str:
    text = normalize_health_text(value)
    return re.sub(r"\s*/\s*$", "", text).strip()


def clean_interaction_text(value: Any) -> str:
    text = normalize_health_text(value)
    return re.sub(r"(?:\n\s*)*복사\s*$", "", text).strip()
