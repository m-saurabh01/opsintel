"""Maps a line inside a stored chunk back to an exact source location for every coordinate kind."""

import json
import re

CELL_RE = re.compile(r"(?:^| \| )([A-Z]{1,3})(\d+): ")
ROW_RE = re.compile(r"^row (\d+): ")
SEP = " | "


def _extra(chunk) -> dict:
    raw = chunk["extra_json"]
    return json.loads(raw) if raw else {}


def cells(chunk, line: str) -> list[dict]:
    if chunk["coord_kind"] != "cell":
        return []
    refs = list(CELL_RE.finditer(line))
    headers = _extra(chunk).get("headers") or {}
    output = []
    for i, match in enumerate(refs):
        end = refs[i + 1].start() if i + 1 < len(refs) else len(line)
        column, row = match.group(1), int(match.group(2))
        value = line[match.end():end].rstrip()
        if i + 1 < len(refs) and value.endswith("|"):
            value = value[:-1].rstrip()
        output.append({
            "cell": f"{column}{row}",
            "column": column,
            "row": row,
            "header": headers.get(column),
            "value": value,
        })
    return output


def locate(chunk, line_idx: int, line: str, match_start: int | None = None) -> dict:
    kind = chunk["coord_kind"]
    if kind == "line":
        first = chunk["start_line"] or 1
        return {"kind": "line", "line": first + line_idx, "start_line": chunk["start_line"],
                "end_line": chunk["end_line"]}
    if kind == "page":
        return {"kind": "page", "page": chunk["page"], "section": chunk["section_path"]}
    extra = _extra(chunk)
    if kind == "section":
        items = extra.get("items") or []
        pos = items[line_idx] if line_idx < len(items) else None
        loc = {"kind": "section", "section": chunk["section_path"]}
        if extra.get("kind") == "table":
            loc.update(table=extra.get("table"), table_row=pos)
        else:
            loc.update(paragraph=pos)
        return loc
    if kind == "cell":
        refs = list(CELL_RE.finditer(line))
        chosen = None
        for m in refs:
            if match_start is None or m.start(1) <= match_start:
                chosen = m
        chosen = chosen or (refs[0] if refs else None)
        loc = {"kind": "cell", "sheet": chunk["sheet"]}
        if chosen:
            col, row = chosen.group(1), int(chosen.group(2))
            loc.update(cell=f"{col}{row}", row=row, column=col, header=(extra.get("headers") or {}).get(col))
        return loc
    if kind == "row":
        m = ROW_RE.match(line)
        loc = {"kind": "row", "row": int(m.group(1)) if m else chunk["row_num"]}
        headers = extra.get("headers") or []
        if m and match_start is not None and match_start >= m.end():
            col = line[m.end():match_start].count(SEP)
            loc.update(column_index=col + 1, column=headers[col] if col < len(headers) else None)
        return loc
    return {"kind": kind}


def heading(chunk) -> str:
    """Describes a whole chunk (viewer section header)."""
    kind = chunk["coord_kind"]
    if kind == "line":
        return f"lines {chunk['start_line']}–{chunk['end_line']}"
    if kind == "page":
        return f"page {chunk['page']}" + (f" · {chunk['section_path']}" if chunk["section_path"] else "")
    if kind == "section":
        extra = _extra(chunk)
        where = f"table {extra.get('table')}" if extra.get("kind") == "table" else "text"
        return f"{chunk['section_path'] or '(before first heading)'} · {where}"
    if kind == "cell":
        return f"{chunk['sheet']} · rows {chunk['start_line']}–{chunk['end_line']}"
    if kind == "row":
        lines = chunk["text"].split("\n")
        last = ROW_RE.match(lines[-1])
        return f"rows {chunk['row_num']}–{last.group(1) if last else '?'}"
    return kind


def label(chunk, line_idx: int, line: str) -> str:
    """Short gutter label for a preview/viewer line."""
    loc = locate(chunk, line_idx, line)
    kind = loc["kind"]
    if kind == "line":
        return str(loc["line"])
    if kind == "page":
        return f"p.{loc['page']}"
    if kind == "section":
        return f"T{loc['table']}.r{loc['table_row']}" if "table" in loc else f"¶{loc.get('paragraph') or '?'}"
    if kind == "cell":
        return f"row {loc['row']}" if "row" in loc else ""
    if kind == "row":
        return f"row {loc['row']}"
    return ""
