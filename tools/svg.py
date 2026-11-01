"""Схемы в SVG: процесс BPMN, паспорт компонента и карта платформы. Стили лежат внутри файла, потому что Docmost показывает его как картинку."""
import html

LANE_H, COL_W, LABEL_W = 96, 136, 118
STYLE = """<style>
text{font-family:Inter,'Segoe UI',Roboto,Arial,sans-serif;fill:#1a237e}
.lane0{fill:#ffffff}.lane1{fill:#f5f6fb}.head{fill:#e8eaf6}
.headtext{font-size:11px;font-weight:700;text-anchor:middle;fill:#1a237e}
.task{fill:#fff;stroke:#3949ab;stroke-width:1.4}.gw{fill:#fff8e1;stroke:#f9a825;stroke-width:1.6}
.start{fill:#e8f5e9;stroke:#43a047;stroke-width:2.2}.end{fill:#eceff1;stroke:#37474f;stroke-width:3}.error{fill:#ffebee;stroke:#e53935;stroke-width:2.2}
.flow{fill:none;stroke:#546e7a;stroke-width:1.2}.arrow{fill:#546e7a}
.text{font-size:10px;text-anchor:middle;fill:#263238}.flowtext{font-size:9.5px;font-weight:700;text-anchor:middle;fill:#00897b}
.gwx{font-size:13px;font-weight:700;text-anchor:middle;fill:#6d4c00}.art{font-size:9px;text-anchor:middle;fill:#5c6bc0}
.title{font-size:15px;font-weight:700;text-anchor:middle;fill:#ffffff}.sub{font-size:11px;text-anchor:middle;fill:#e8eaf6}
.core{fill:#3f51b5}.port{fill:#fff;stroke:#c5cae9;stroke-width:1.2}.portext{fill:#fff3e0;stroke:#ef6c00;stroke-width:1.2}
.name{font-size:12px;font-weight:600;text-anchor:middle;fill:#1a237e}.code{font-size:10px;font-weight:700;text-anchor:middle;fill:#00897b}
.col{font-size:12px;font-weight:700;text-anchor:middle;fill:#5c6bc0}
.zone{fill:#f5f6fb;stroke:#c5cae9;stroke-width:1.2}.zonetext{font-size:13px;font-weight:700;fill:#3949ab}
.tile{fill:#fff;stroke:#7986cb;stroke-width:1.4}.tiledesc{font-size:10px;text-anchor:middle;fill:#546e7a}
.ext{fill:#fff3e0;stroke:#ef6c00;stroke-width:1.2}.count{font-size:10px;text-anchor:middle;fill:#3949ab;font-weight:600}
</style>"""
MARKER = '<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="arrow"/></marker></defs>'


def wrap(text, limit=18):
    words, lines, current = str(text).split(), [], ""
    for word in words:
        if len(current) + len(word) + 1 > limit and current:
            lines.append(current)
            current = word
        else:
            current = (current + " " + word).strip()
    return lines + ([current] if current else [])


def esc(text):
    return html.escape(str(text))


def start(width, height):
    return [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">', STYLE, MARKER]


def text_lines(out, x, y, lines, css, step=13):
    out += [f'<text x="{x}" y="{y + index * step}" class="{css}">{esc(line)}</text>' for index, line in enumerate(lines)]


def bpmn(unit, lane_title):
    """Процесс с дорожками. Шаги идут слева направо в порядке описания."""
    steps = unit["steps"]
    lanes = list(dict.fromkeys(step.get("lane") or lane_title(step["actor"]) for step in steps))
    column = {step["id"]: index for index, step in enumerate(steps)}
    row = {step["id"]: lanes.index(step.get("lane") or lane_title(step["actor"])) for step in steps}
    position = {key: (LABEL_W + column[key] * COL_W + COL_W / 2, row[key] * LANE_H + LANE_H / 2) for key in column}
    width, height = LABEL_W + len(steps) * COL_W + 10, len(lanes) * LANE_H + 34
    out = start(width, height)
    for index, lane in enumerate(lanes):
        y = index * LANE_H
        out.append(f'<rect x="0" y="{y}" width="{width}" height="{LANE_H}" class="lane{index % 2}"/>')
        out.append(f'<rect x="0" y="{y}" width="{LABEL_W - 8}" height="{LANE_H}" class="head"/>')
        text_lines(out, (LABEL_W - 8) / 2, y + LANE_H / 2 - 4, wrap(lane, 14), "headtext")
    half = {"task": 56, "gateway": 20, "start": 15, "end": 15, "error": 15}
    kinds = {step["id"]: step.get("type", "task") for step in steps}
    for step in steps:
        x1, y1 = position[step["id"]]
        for item in step.get("next", []):
            if item["to"] not in position:
                continue
            x2, y2 = position[item["to"]]
            if column[item["to"]] > column[step["id"]]:
                sx, ex = x1 + half[kinds[step["id"]]], x2 - half[kinds[item["to"]]]
                path = f"M{sx},{y1} C{sx + 35},{y1} {ex - 35},{y2} {ex},{y2}"
                lx, ly = (sx + ex) / 2, (y1 + y2) / 2 - 5
            else:
                base = len(lanes) * LANE_H + 20
                path = f"M{x1},{y1 + 20} C{x1},{base} {x2},{base} {x2},{y2 + 20}"
                lx, ly = (x1 + x2) / 2, base - 4
            out.append(f'<path d="{path}" class="flow" marker-end="url(#ar)"/>')
            if item.get("label"):
                out.append(f'<text x="{lx}" y="{ly}" class="flowtext">{esc(item["label"])}</text>')
    for step in steps:
        x, y = position[step["id"]]
        kind = kinds[step["id"]]
        lines = wrap(step["title"])[:3]
        if kind == "task":
            out.append(f'<rect x="{x - 56}" y="{y - 25}" width="112" height="50" rx="9" class="task"/>')
            ty = y - (len(lines) - 1) * 6.5 + 4
        elif kind == "gateway":
            out.append(f'<path d="M{x},{y - 20} L{x + 20},{y} L{x},{y + 20} L{x - 20},{y} z" class="gw"/><text x="{x}" y="{y + 5}" class="gwx">×</text>')
            ty = y - 26 - (len(lines) - 1) * 13
        else:
            out.append(f'<circle cx="{x}" cy="{y}" r="15" class="{kind}"/>')
            if kind == "error":
                out.append(f'<text x="{x}" y="{y + 5}" class="gwx">⚡</text>')
            ty = y + 30
        text_lines(out, x, ty, lines, "text")
        artifacts = step.get("artifacts", [])
        if artifacts:
            note = ", ".join(artifacts)
            note = note if len(note) < 30 else note[:28] + "…"
            out.append(f'<text x="{x}" y="{y + 37 if kind == "task" else ty + len(lines) * 13 + 2}" class="art">📄 {esc(note)}</text>')
    return "".join(out) + "</svg>"


def passport(title, subtitle, inputs, outputs):
    """Компонент в центре, слева что приходит, справа что уходит. Элемент это пара (код, имя)."""
    rows = max(len(inputs), len(outputs), 1)
    row_h, box_w, width = 54, 230, 1040
    height = max(rows * row_h + 60, 170)
    core_w, core_h = 300, 110
    core_x, core_y = (width - core_w) / 2, (height - core_h) / 2 + 8
    out = start(width, height)
    text_lines(out, box_w / 2 + 10, 20, ["Входы"], "col")
    text_lines(out, width - box_w / 2 - 10, 20, ["Выходы"], "col")
    out.append(f'<rect x="{core_x}" y="{core_y}" width="{core_w}" height="{core_h}" rx="14" class="core"/>')
    text_lines(out, width / 2, core_y + 44, wrap(title, 26)[:2], "title", 19)
    text_lines(out, width / 2, core_y + 84, wrap(subtitle, 44)[:2], "sub", 14)

    def column(items, x, left):
        gap = (height - 40) / max(len(items), 1)
        for index, (code, name, external) in enumerate(items):
            y = 34 + gap * index + (gap - 42) / 2
            out.append(f'<rect x="{x}" y="{y}" width="{box_w}" height="42" rx="9" class="{"portext" if external else "port"}"/>')
            text_lines(out, x + box_w / 2, y + 17, wrap(name, 34)[:1], "name")
            text_lines(out, x + box_w / 2, y + 33, [code], "code")
            sx, ex = (x + box_w, core_x) if left else (core_x + core_w, x)
            cy = core_y + core_h / 2
            ny = y + 21
            a, b = (ny, cy) if left else (cy, ny)
            out.append(f'<path d="M{sx},{a} C{sx + 45},{a} {ex - 45},{b} {ex},{b}" class="flow" marker-end="url(#ar)"/>')

    column(inputs, 10, True)
    column(outputs, width - box_w - 10, False)
    return "".join(out) + "</svg>"


def score(title, value, status, parts, roles):
    """Полоска готовности: значение, разбивка по частям и подтверждения ролей."""
    width, height = 1040, 118
    out = start(width, height)
    color = "#2e7d32" if value >= 75 else "#f9a825" if value >= 40 else "#e53935"
    out.append(f'<rect x="1" y="1" width="{width - 2}" height="{height - 2}" rx="12" fill="#f5f6fb" stroke="#c5cae9"/>')
    out.append(f'<text x="24" y="33" style="font-size:12px;font-weight:700;letter-spacing:1px;fill:#546e7a">ГОТОВНОСТЬ · {esc(title)}</text>')
    out.append(f'<rect x="340" y="23" width="400" height="11" rx="5" fill="#e0e0e0"/><rect x="340" y="23" width="{4 * value}" height="11" rx="5" fill="{color}"/>')
    out.append(f'<text x="754" y="34" style="font-size:15px;font-weight:700;fill:{color}">{value}%</text><text x="808" y="34" style="font-size:12px;fill:#546e7a">{esc(status)}</text>')
    x = 24
    for name, got, limit in parts:
        chunk = f"{name} {got}/{limit}"
        out.append(f'<text x="{x}" y="66" style="font-size:12px;fill:#37474f">{esc(chunk)}</text>')
        x += 24 + len(chunk) * 6.9
    x = 24
    for role, done, total in roles:
        fill = "#2e7d32" if done == total else "#9e9e9e"
        out.append(f'<circle cx="{x + 11}" cy="94" r="11" fill="{fill}"/><text x="{x + 11}" y="98" style="font-size:11px;font-weight:700;text-anchor:middle;fill:#fff">{esc(role[0])}</text>')
        out.append(f'<text x="{x + 27}" y="98" style="font-size:11px;fill:#546e7a">{done}/{total}</text>')
        x += 76
    if not roles:
        out.append('<text x="24" y="98" style="font-size:11px;fill:#546e7a">Подтверждений ролей нет</text>')
    return "".join(out) + "</svg>"


def platform_map(zones, externals):
    """Зоны с плитками компонентов и внешние системы. Зона это (название, [(заголовок, описание, счётчик)])."""
    tile_w, tile_h, gap, per_row = 216, 92, 14, 3
    width = per_row * (tile_w + gap) + 40 + 210
    y, out_body = 14, []
    for title, tiles in zones:
        lines = (len(tiles) + per_row - 1) // per_row
        zone_h = lines * (tile_h + gap) + 42
        out_body.append(f'<rect x="10" y="{y}" width="{per_row * (tile_w + gap) + 14}" height="{zone_h}" rx="14" class="zone"/>')
        out_body.append(f'<text x="28" y="{y + 25}" class="zonetext">{esc(title)}</text>')
        for index, (name, description, count) in enumerate(tiles):
            x = 24 + index % per_row * (tile_w + gap)
            ty = y + 36 + index // per_row * (tile_h + gap)
            out_body.append(f'<rect x="{x}" y="{ty}" width="{tile_w}" height="{tile_h}" rx="11" class="tile"/>')
            local = []
            text_lines(local, x + tile_w / 2, ty + 22, [name], "name")
            text_lines(local, x + tile_w / 2, ty + 42, wrap(description, 34)[:2], "tiledesc")
            text_lines(local, x + tile_w / 2, ty + 80, [count], "count")
            out_body += local
        y += zone_h + 14
    height = max(y, len(externals) * 62 + 40)
    ex = per_row * (tile_w + gap) + 44
    out_body.append(f'<text x="{ex + 90}" y="30" class="col">Внешние системы</text>')
    for index, name in enumerate(externals):
        ty = 44 + index * 62
        out_body.append(f'<rect x="{ex}" y="{ty}" width="182" height="48" rx="10" class="ext"/>')
        local = []
        text_lines(local, ex + 91, ty + 28, wrap(name, 24)[:1], "name")
        out_body += local
    return "".join(start(width, height) + out_body) + "</svg>"
