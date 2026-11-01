"""Страницы для человека: собираются из YAML и отчёта проверок, вручную не ведутся."""
import collections
import re

import yaml

import svg

FOLDERS = ("actors", "processes", "services", "systems", "functions", "components", "data", "stores", "flows", "integrations", "nodes")
LABEL_LIMIT = 44
EXAMPLES = 3


def load_yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class Model:
    def __init__(self, root):
        self.root = root
        self.arch = root / "docs" / "architecture"
        for name in FOLDERS:
            setattr(self, name, {u["id"]: u for u in map(load_yaml, self.paths(name)) if isinstance(u, dict)})
        self.blocks = [(p.parent.parent.name if "components" in p.parts[-4:-1] else p.parent.name, load_yaml(p)) for p in self.paths("blocks")]
        self.sequences = [load_yaml(p) for p in self.paths("sequences")]
        self.endpoints = {p.parent.name: load_yaml(p) for p in self.arch.glob("components/*/endpoints.yaml")}
        self.approvals = {p.parent.name: load_yaml(p)["rows"] for p in self.arch.glob("components/*/approvals.yaml")}
        decisions = self.arch / "decisions"
        self.decisions = [load_yaml(decisions / f"{d}.yaml") for d in load_yaml(decisions / "_order.yaml")["order"]] if decisions.exists() else []
        report = root / "_quality" / "check-report.yaml"
        self.report = load_yaml(report) if report.exists() else {}

    def paths(self, name):
        """Единицы типа name: из общей папки и из папок компонентов."""
        if name == "components":
            return [p for p in sorted(self.arch.glob("components/*.yaml")) if not p.name.startswith("_")] + sorted(self.arch.glob("components/*/component.yaml"))
        flat =sorted((self.arch / name).rglob("*.yaml")) if (self.arch / name).exists() else []
        return [p for p in flat + sorted(self.arch.glob(f"components/*/{name}/*.yaml")) if not p.name.startswith("_")]

    def sequence_block(self, key):
        item = next((s for s in self.sequences if s["id"] == key), None)
        return f"```mermaid\n{item['diagram']}\n```" if item else ""

    def code_pages(self):
        """Куда ведёт код из текста: требование к своему компоненту, решение и канал к реестрам."""
        pages = {d["id"]: "decisions" for d in self.decisions}
        pages.update({key: "registers" for key in self.integrations})
        for story in load_stories(self):
            pages[story.get("source", story["id"])] = f"stories:{story['component']}"
            for req in story["reqs"]:
                pages.setdefault(req, f"reqs:{story['component']}")
        return pages

    def term_pages(self):
        """Имена, у которых есть своя страница: компоненты, типы данных и таблицы."""
        pages = {unit["title"]: f"comp:{key}" for key, unit in self.components.items()}
        pages.update({key: f"type:{key}" for key, unit in self.data.items() if unit["class"] == "contract"})
        for store in self.stores.values():
            if store["owner"] in self.components:
                pages.update({table: f"datamodel:{store['owner']}" for table in store["tables"]})
        return pages

    def file(self, name, key):
        path = self.arch / name
        return load_yaml(path)[key] if path.exists() else []

    def system_of(self, name):
        return self.components[name]["system"] if name in self.components else name

    def title(self, key):
        for name in FOLDERS:
            if key in getattr(self, name):
                return getattr(self, name)[key]["title"]
        return key


def node(key):
    return "n_" + re.sub(r"\W", "_", key)


def label(text, limit=LABEL_LIMIT):
    """Подпись для Mermaid: без символов разметки и не длиннее строки на схеме."""
    text = re.sub(r"[`\"\[\]{}()<>|#;]", " ", str(text))
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[:limit - 1].rsplit(" ", 1)[0] + "…"


PALETTE = [
    "classDef self fill:#c5cae9,stroke:#3949ab,color:#1a237e,stroke-width:2px",
    "classDef comp fill:#e8eaf6,stroke:#5c6bc0,color:#1a237e",
    "classDef user fill:#e3f2fd,stroke:#1565c0,color:#0d47a1",
    "classDef ext fill:#fff3e0,stroke:#ef6c00,color:#e65100",
    "classDef store fill:#e8f5e9,stroke:#43a047,color:#1b5e20",
    "classDef start fill:#e8f5e9,stroke:#43a047,color:#1b5e20,stroke-width:2px",
    "classDef task fill:#ffffff,stroke:#3949ab,color:#1a237e",
    "classDef gate fill:#fff8e1,stroke:#f9a825,color:#6d4c00",
    "classDef error fill:#ffebee,stroke:#e53935,color:#b71c1c,stroke-width:2px",
    "classDef finish fill:#eceff1,stroke:#37474f,color:#263238,stroke-width:3px",
]
SHAPES = {"start": ('(("', '"))', "start"), "task": ('["', '"]', "task"), "gateway": ('{"', '"}', "gate"),
          "error": ('(["', '"])', "error"), "end": ('(("', '"))', "finish")}
LANE = "fill:#f5f6fb,stroke:#c5cae9,color:#3949ab"
LEGEND = "🟢 начало · ▭ задача · 🔶 развилка · 🔴 ошибка · ⚫ конец"


def diagram(lines):
    return "\n".join(["```mermaid", *lines, *["  " + line for line in PALETTE], "```"])


def table(header, rows):
    rows = [list(row) for row in rows]
    keep = [i for i in range(len(header)) if i == 0 or any(str(row[i]).strip() not in ("", "—", "нет") for row in rows)]
    lines = ["| " + " | ".join(header[i] for i in keep) + " |", "| " + " | ".join("---" for _ in keep) + " |"]
    lines += ["| " + " | ".join(str(row[i]).replace("|", "/").replace("\n", " ") for i in keep) + " |" for row in rows]
    return "\n".join(lines)


def codes(items):
    return ", ".join(str(item) for item in items) or "нет"


def comp(model, key):
    return f"[[comp:{key}|{model.title(key)}]]" if key in model.components else model.title(key)


def names(model, items):
    return ", ".join(model.title(item) for item in items) or "нет"


def c1(model):
    lines = ["graph LR"]
    consumers = {c for s in model.services.values() for c in s["consumers"] if c in model.actors}
    for key in sorted(consumers):
        lines.append(f'  {node(key)}(["{label(model.actors[key]["title"])}"]):::user')
    for key, unit in model.systems.items():
        style = "self" if unit["kind"] == "own" else "ext"
        lines.append(f'  {node(key)}["{label(unit["title"])}"]:::{style}')
    edges = collections.defaultdict(list)
    for key, unit in model.integrations.items():
        ends = model.system_of(unit["from"]), model.system_of(unit["to"])
        if ends[0] != ends[1]:
            edges[ends].append(key)
    lines += [f'  {node(a)} -->|"{label(", ".join(items))}"| {node(b)}' for (a, b), items in sorted(edges.items())]
    links = {(c, s["provider"]) for s in model.services.values() for c in s["consumers"] if c in model.actors}
    lines += [f"  {node(c)} --> {node(p)}" for c, p in sorted(links)]
    parts = ["Кто пользуется системой и с какими внешними системами она связана. На стрелках коды интеграций.", diagram(lines)]
    if model.services:
        parts += ["## Сервисы", table(["Сервис", "Потребители", "Обязательства"], [
            [s["title"], names(model, s["consumers"]), "; ".join(dict.fromkeys(o["text"] for o in s["objectives"]))] for s in model.services.values()])]
    return "\n\n".join(parts)


def c2(model):
    lines = ["graph LR"]
    for system, unit in model.systems.items():
        inner = {k: u for k, u in model.components.items() if u["system"] == system}
        if not inner:
            lines.append(f'  {node(system)}["{label(unit["title"])}"]:::ext')
            continue
        lines.append(f'  subgraph {node("sys_" + system)}["{label(unit["title"])}"]')
        for key, item in inner.items():
            lines.append(f'    {node(key)}["{label(item["title"])}"]:::comp')
        lines.append("  end")
        lines.append(f"  style {node('sys_' + system)} {LANE}")
    for key, unit in model.stores.items():
        lines.append(f'  {node(key)}[("{label(unit["title"], 30)}")]:::store')
        if unit["owner"] in model.components:
            lines.append(f"  {node(unit['owner'])} --> {node(key)}")
    for key, unit in model.integrations.items():
        lines.append(f'  {node(unit["from"])} -->|"{key}"| {node(unit["to"])}')
    count = collections.Counter(owner for owner, _ in model.blocks)
    parts = ["Контейнеры, хранилища и каналы между ними. На стрелках коды интеграций.", diagram(lines), "## Компоненты",
             table(["Компонент", "Отвечает за", "Технология", "Размещён в", "Блоков"],
                   [[u["title"], u["responsibility"], u.get("tech", ""), model.title(u["host"]) if u.get("host") else "", count[k]] for k, u in model.components.items()])]
    return "\n\n".join(parts)


def block_diagram(blocks):
    lines = ["graph LR"]
    titles = {block["title"]: block["id"] for block in blocks}
    for block in blocks:
        lines.append(f'  {node(block["id"])}["{label(block["title"])}"]:::comp')
    outside, seen = {}, set()
    for block in blocks:
        for item in block.get("io", []):
            other = item["with"]
            target = titles.get(other) or outside.setdefault(other, f"ext_{len(outside)}")
            pair = (target, block["id"]) if item["dir"] == "in" else (block["id"], target)
            if pair not in seen and pair[0] != pair[1]:
                seen.add(pair)
                lines.append(f"  {node(pair[0])} --> {node(pair[1])}")
    lines += [f'  {node(key)}["{label(name, 30)}"]:::ext' for name, key in outside.items()]
    return diagram(lines)


def c3(model):
    fill = model.report.get("coverage", {}).get("blocks", {})
    parts = ["Блоки внутри компонентов. Прямоугольник это блок компонента, наклонная фигура это внешний участник."]
    groups = collections.defaultdict(list)
    for owner, block in model.blocks:
        groups[owner].append(block)
    for owner, blocks in groups.items():
        rows = [[b["title"], "; ".join(b["does"][:2]), codes(b["reqs"][:4]), f"{fill.get(b['id'], {}).get('filled', '?')} %"] for b in blocks]
        parts += [f"## {model.title(owner)}", block_diagram(blocks), table(["Блок", "Что делает", "Требования", "Заполнено"], rows)]
    return "\n\n".join(parts)


def card(block):
    data = block["data"] if isinstance(block["data"], str) else ", ".join(f"{row['table']} ({row['access']})" for row in block["data"])
    params = block["params"] if isinstance(block["params"], str) else codes(block["params"])
    io = "; ".join(f"{'←' if item['dir'] == 'in' else '→'} {item['with']}: {item['what']}" for item in block["io"])
    fields = [("Что делает", "; ".join(block["does"])), ("Технология", block.get("tech", "")), ("Истории", codes(block.get("stories", []))),
              ("Входы и выходы", io), ("Данные", data), ("Параметры", params), ("Требования", codes(block["reqs"])),
              ("Задачи", codes(block.get("tasks", []))), ("При сбое", block["on_failure"]), ("Почему так", block.get("why", "")),
              ("Исследование", f"[[rnd:{block['rnd']}|{block['rnd']}]]" if block.get("rnd") else "")]
    return f"### {block['title']}\n\n" + table(["Поле", "Значение"], fields)


def cards(model, only=None):
    parts = []
    current = None
    for owner, block in model.blocks:
        if only and owner != only:
            continue
        if owner != current:
            parts.append(f"## {model.title(owner)}")
            current = owner
        parts.append(card(block))
    return "\n\n".join(parts) or "Карточек пока нет."


def process_diagram(model, unit):
    """Схема с дорожками: если у шагов есть переходы, рисуются они, иначе шаги идут цепочкой."""
    lines = ["graph LR"]
    steps = [(step.get("id", f"step_{index}"), step) for index, step in enumerate(unit["steps"], 1)]
    lanes = collections.defaultdict(list)
    for key, step in steps:
        lanes[step["actor"]].append((key, step))
    for lane, items in lanes.items():
        lines.append(f'  subgraph {node("lane_" + lane)}["{label(model.title(lane), 30)}"]')
        for key, step in items:
            left, right, style = SHAPES[step.get("type", "task")]
            lines.append(f'    {node(key)}{left}{label(step["title"], 70)}{right}:::{style}')
        lines.append("  end")
        lines.append(f"  style {node('lane_' + lane)} {LANE}")
    known = {key for key, _ in steps}
    if any(step.get("next") for _, step in steps):
        for key, step in steps:
            for item in step.get("next", []):
                if item["to"] in known:
                    text = f'|"{label(item["label"], 24)}"|' if item.get("label") else ""
                    lines.append(f"  {node(key)} -->{text} {node(item['to'])}")
    else:
        lines += [f"  {node(a[0])} --> {node(b[0])}" for a, b in zip(steps, steps[1:])]
    return diagram(lines)


def load_stories(model):
    stories = [load_yaml(path) for path in model.paths("stories")]
    return sorted(stories, key=lambda s: [int(part) for part in s["number"].split(".")])


def story_card(story, blocks):
    """Карточка истории: выноска с ролью, целью и критериями."""
    criteria = "\n".join(f"- [ ] {item}" for item in story["accept"])
    goal = f"**Хочу:** {story['want']}" + (f"\n\n**Чтобы:** {story['so_that']}" if story.get("so_that") else "")
    links = [f"**Требования:** {codes(story['reqs'])}"]
    if blocks:
        links.append(f"**Блоки:** {', '.join(blocks)}")
    head = f"### {story.get('source', story['id'])} · история {story['number']}"
    return f"{head}\n\n:::info\n**{story['role']}**\n\n{goal}\n:::\n\n**Критерии приёмки**\n\n{criteria}\n\n{' · '.join(links)}"


def process_picture(model, unit):
    return f"{{{{svg:bpmn:{unit['id']}}}}}" if all(step.get("id") for step in unit["steps"]) else process_diagram(model, unit)


def stories_view(model, component):
    parts = []
    processes = [u for u in model.processes.values() if u.get("component") == component]
    for number, unit in enumerate(processes, 1):
        parts += [f"## Процесс {number}. {unit['title']}", f"Покрывает истории: {codes(unit.get('stories', []))}", process_picture(model, unit), LEGEND]
    stories = [s for s in load_stories(model) if s["component"] == component]
    by_story = collections.defaultdict(list)
    for owner, block in model.blocks:
        for number in block.get("stories", []):
            by_story[number].append(block["title"])
    if stories:
        parts += ["## Сводка", table(["История", "Роль", "Что хочет", "Критериев"], [[s.get("source", s["id"]), s["role"], s["want"], len(s["accept"])] for s in stories]), "## Истории"]
        parts += [story_card(s, by_story[s["number"]]) for s in stories]
    return "\n\n".join(parts) or "Историй пока нет."


def ports(model, component):
    """Входы и выходы компонента: что и по какому каналу приходит и уходит."""
    inputs, outputs = [], []
    for key, unit in model.integrations.items():
        if unit["to"] == component:
            inputs.append((key, unit["from"], unit))
        elif unit["from"] == component:
            outputs.append((key, unit["to"], unit))
    return inputs, outputs


def svg_for(name, model):
    """Строит картинку по имени метки: bpmn:<процесс>, passport:<компонент> или map."""
    kind, _, key = name.partition(":")
    if kind == "bpmn":
        return svg.bpmn(model.processes[key], model.title)
    if kind == "score":
        state = component_score(model, key)
        return svg.score(model.title(key), state["value"], state["status"], state["parts"], state["roles"])
    if kind == "passport":
        inputs, outputs = ports(model, key)
        pair = lambda items: [(code, model.title(other), other not in model.components) for code, other, _ in items]
        return svg.passport(model.title(key), model.components[key]["responsibility"], pair(inputs), pair(outputs))
    stories = load_stories(model)
    tiles = collections.defaultdict(list)
    for key_, unit in model.components.items():
        count = sum(s["component"] == key_ for s in stories)
        blocks = sum(owner == key_ for owner, _ in model.blocks)
        tiles[unit["system"]].append((unit["title"], unit["responsibility"], f"{count} историй · {blocks} блоков"))
    zones = [(model.title(system), items) for system, items in tiles.items()]
    return svg.platform_map(zones, [u["title"] for k, u in model.systems.items() if u["kind"] != "own"])


def home(model):
    rows = []
    stories = load_stories(model)
    for key, unit in model.components.items():
        inputs, outputs = ports(model, key)
        rows.append([f"**{comp(model, key)}**", unit["responsibility"], sum(s["component"] == key for s in stories), sum(o == key for o, _ in model.blocks), len(inputs), len(outputs)])
    state = model.report.get("readiness", {})
    links = " · ".join(f"[[{k}|{t}]]" for k, t in (("readiness", "Панель готовности"), ("c1", "C1"), ("c2", "C2"), ("dfd", "Потоки данных"), ("er", "Модель данных"), ("registers", "Реестры"), ("decisions", "Решения")))
    return "\n\n".join([f":::info\nГотовность **{state.get('score', '?')} из 100**, блокеров **{model.report.get('blockers', '?')}**. Разделы: {links}\n:::", "## Компоненты",
                          table(["Компонент", "Отвечает за", "Историй", "Блоков", "Входов", "Выходов"], rows)])


def port_rows(model, items):
    return [[code, comp(model, other), unit["purpose"], unit["protocol"], unit["timeout"]] for code, other, unit in items]


def component_view(model, key):
    unit = model.components[key]
    inputs, outputs = ports(model, key)
    stories = [s for s in load_stories(model) if s["component"] == key]
    blocks = [b for o, b in model.blocks if o == key]
    parts = [f":::info\n{unit.get('purpose') or unit['responsibility']}\n:::", f"{{{{svg:score:{key}}}}}", f"{{{{svg:passport:{key}}}}}"]
    parts.append(table(["Историй", "Блоков", "Входов", "Выходов"], [[len(stories), len(blocks), len(inputs), len(outputs)]]))
    if unit.get("does"):
        parts += ["## Что делает", "\n".join(f"- {item}" for item in unit["does"])]
    if unit.get("chain"):
        parts += ["## Место в цепочке", " → ".join(comp(model, item) for item in unit["chain"])]
    if inputs:
        parts += ["## Входы", table(["Канал", "Откуда", "Что", "Протокол", "Таймаут"], port_rows(model, inputs))]
    if outputs:
        parts += ["## Выходы", table(["Канал", "Куда", "Что", "Протокол", "Таймаут"], port_rows(model, outputs))]
    return "\n\n".join(parts)


TABS = (("comp", ""), ("stories", "User Stories"), ("integrations", "Интеграции"), ("reqs", "Спека"), ("trace", "Трассировка"), ("blocks", "Блоки"),
        ("datamodel", "Данные и потоки"), ("sequences", "Сценарии"), ("how", "Как работает"), ("tech", "Deploy"), ("find", "Замечания"))


def tab_bar(key, current, pages, model):
    """Разделы компонента: только страницы, которые есть, текущая без перехода."""
    items = []
    for tab, title in TABS:
        name = f"{tab}:{key}"
        title = title or model.title(key)
        if name == current:
            items.append(f"**{title}**")
        elif name in pages:
            items.append(f"[[{name}|{title}]]")
    return " · ".join(items)


SCALE = ((90, "готова"), (75, "почти"), (60, "в работе"), (40, "черновик"), (0, "заготовка"))


def requirements(model, key):
    """Требования из prd.md компонента: код, заголовок, текст, число сценариев."""
    path = model.arch / "components" / key / "prd.md"
    if not path.exists():
        return []
    found = []
    source = re.sub(r"(?<!!)\[([^\]]+)\]\((?!https?:)[^)]*\)", r"\1", path.read_text(encoding="utf-8"))
    for match in re.finditer(r"^#### (FR-\d+): (.+?)\n(.*?)(?=^#{3,4} |\Z)", source, re.M | re.S):
        found.append((match.group(1), match.group(2), match.group(3), len(re.findall(r"^- ", match.group(3), re.M))))
    return found


def component_score(model, key):
    """Готовность по критериям спеки: измеримый минимум, а не доказательство полноты."""
    reqs = requirements(model, key)
    total = max(len(reqs), 1)
    stories = [s for s in load_stories(model) if s["component"] == key]
    linked = {r for s in stories for r in s["reqs"]}
    blocks = [b for o, b in model.blocks if o == key]
    bound = {r for d in model.decisions for r in d["binds"]}
    inputs, outputs = ports(model, key)
    targets = {row["target"] for row in model.file("fmea.yaml", "rows")}
    keys = {code for code, _, _ in inputs + outputs}
    how = (model.arch / "components" / key / "docs" / "how.md").exists()
    parts = [("Формат", round(15 * sum(bool(re.search(r"SHALL|MUST", text)) for _, _, text, _ in reqs) / total), 15),
             ("Сценарии", round(25 * sum(min(cases, 3) / 3 for *_, cases in reqs) / total), 25),
             ("Трассировка", round(20 * sum(code in linked for code, *_ in reqs) / total), 20),
             ("Обоснование", 5 * any(b.get("rnd") for b in blocks) + round(5 * sum(code in bound for code, *_ in reqs) / total), 10),
             ("Интерфейсы, отказы", 5 * bool(keys) + 5 * bool(targets & (keys | {key})) + 5 * any(r.startswith("NFR") for s in stories for r in s["reqs"]), 15),
             ("Связность", 5 * how + 5 * any(s.get("component") == key for s in model.sequences) + 5 * bool(blocks), 15)]
    rows = model.approvals.get(key, [])
    roles = collections.defaultdict(lambda: [0, 0])
    for row in rows:
        roles[row["role"]][1] += 1
        roles[row["role"]][0] += row["decision"] == "✅"
    value = sum(got for _, got, _ in parts)
    if any(row["decision"] != "✅" for row in rows):
        value = min(value, 90)
    return {"value": value, "status": next(name for limit, name in SCALE if value >= limit), "parts": parts, "roles": [(r, d, t) for r, (d, t) in roles.items()]}


def spec_view(model, key):
    """Спека компонента: полоска готовности и требования с тем, что их подтверждает."""
    stories = [s for s in load_stories(model) if s["component"] == key]
    blocks = [b for o, b in model.blocks if o == key]
    parts = [f"{{{{svg:score:{key}}}}}"]
    for code, title, text, cases in requirements(model, key):
        linked = [s.get("source", s["id"]) for s in stories if code in s["reqs"]]
        cards_ = [b["title"] for b in blocks if code in b["reqs"]]
        decisions = [d["id"] for d in model.decisions if code in d["binds"]]
        confirmed = [row for row in model.approvals.get(key, []) if row["req"] == code]
        marks = [f"**Истории:** {codes(linked)}" if linked else "**Истории:** нет"]
        if cards_:
            marks.append(f"**Блоки:** {', '.join(cards_)}")
        if decisions:
            marks.append(f"**Решения:** {codes(decisions)}")
        if confirmed:
            marks.append(f"**Роли:** {sum(r['decision'] == '✅' for r in confirmed)} из {len(confirmed)}")
        parts += [f"## {code}. {title}", f":::info\n{' · '.join(marks)}\n:::", text.strip().replace("**Consequences (testable):**", "**Сценарии**")]
    return "\n\n".join(parts) or "Требований пока нет."


def neighbours(model, key):
    """Схема соседей: сплошная стрелка это вызов, пунктир это общая инфраструктура, ↩ значит данные в ответе."""
    lines = ["graph LR", f'  {node(key)}["{label(model.title(key))}"]:::self']
    pairs, seen = collections.defaultdict(list), set()
    dotted = collections.defaultdict(list)
    for code, unit in model.integrations.items():
        tag = code + ("↩" if unit.get("data_in_response") else "")
        if key in (unit["from"], unit["to"], unit.get("via")):
            chain = [x for x in (unit["from"], unit.get("via"), unit["to"]) if x]
            for a, b in zip(chain, chain[1:]):
                pairs[(a, b)].append(tag)
        elif key in unit.get("also", []):
            dotted[unit["from"]].append(code)
    for name in {x for pair in pairs for x in pair} | set(dotted):
        if name != key:
            style = "comp" if name in model.components else "ext"
            lines.append(f'  {node(name)}["{label(model.title(name))}"]:::{style}')
    lines += [f'  {node(a)} -->|"{label(", ".join(tags), 30)}"| {node(b)}' for (a, b), tags in pairs.items()]
    lines += [f'  {node(key)} -.-|"{label(", ".join(tags), 30)}"| {node(other)}' for other, tags in dotted.items()]
    return diagram(lines)


def channel_data(model, code):
    return list(dict.fromkeys(item for flow in model.flows.values() if flow.get("over") == code for item in flow["objects"]))


def integration_card(model, key, code, unit):
    """Карточка канала: одна запись показывается у обеих сторон."""
    source, target = (unit["to"], unit["from"]) if unit.get("data_in_response") else (unit["from"], unit["to"])
    direction, kind = ("отдаёт", "success") if source == key else ("получает", "info") if target == key else ("участвует", "warning")
    route = " → ".join(comp(model, item) for item in [source, unit.get("via"), target] if item)
    note = f" (вызывает {comp(model, unit['from'])}, данные в ответе)" if unit.get("data_in_response") else ""
    lines = [f":::{kind}", f"**{code} · {direction}** · {route}{note}", "", unit["purpose"], "",
             f"**Канал:** {unit['protocol']} · **Доступ:** {unit['auth']} · **Режим:** {unit.get('mode', 'не задан')} · **Таймаут:** {unit['timeout']} · **Повтор:** {unit['retry']}"]
    data = channel_data(model, code)
    if data:
        lines += ["", "**Данные:** " + " ".join(f"`{item}`" for item in data)]
    rows = [row for rows_ in model.endpoints.values() for row in rows_["rows"] if code in row.get("via", [])]
    if rows:
        lines += [""] + [f"- **{row['method']}** `{row['path']}` {row.get('does', '')}" for row in rows[:8]]
        if len(rows) > 8:
            lines.append(f"- ещё {len(rows) - 8} в разделе API")
    return "\n".join(lines + [":::"])


def integrations_view(model, key):
    inputs, outputs = ports(model, key)
    shared = [(code, None, unit) for code, unit in model.integrations.items() if key in unit.get("also", []) or unit.get("via") == key]
    parts = ["Стрелка показывает, кто вызывает кого. ↩ значит, что данные приходят в ответе. Пунктир это общая инфраструктура. 🔵 получает, 🟢 отдаёт, 🟡 участвует.", neighbours(model, key), "## Интеграции"]
    parts += [integration_card(model, key, code, unit) for code, _, unit in inputs + outputs + shared]
    used = list(dict.fromkeys(item for code, _, _ in inputs + outputs + shared for item in channel_data(model, code)))
    contracts = [item for item in used if item in model.data and model.data[item]["class"] == "contract"]
    if contracts:
        parts += ["## Контракты данных", table(["Тип", "Назначение"], [[f"`{item}`", model.data[item]["title"]] for item in contracts])]
    api = model.endpoints.get(key)
    if api:
        parts.append("## API")
        parts += api.get("notes", [])
        groups = collections.defaultdict(list)
        for row in api["rows"]:
            groups[row.get("section", "")].append(row)
        for section, rows in groups.items():
            if section:
                parts.append(f"### {section}")
            parts.append(table(["Метод", "Путь", "Статус", "Что делает", "Кто вызывает", "Канал"],
                               [[f"**{r['method']}**", f"`{r['path']}`", r.get("status", ""), r.get("does", ""), r.get("caller", ""), codes(r.get("via", []))] for r in rows]))
    return "\n\n".join(parts)


def trace_view(model, key):
    """Что подтверждает требование: история, блок, решение, исследование."""
    stories = [s for s in load_stories(model) if s["component"] == key]
    blocks = [b for o, b in model.blocks if o == key]
    rows = []
    for req in sorted({r for s in stories for r in s["reqs"]}, key=lambda c: (c[0] != "F", int(c.split("-")[1]))):
        linked = [s.get("source", s["id"]) for s in stories if req in s["reqs"]]
        cards_ = [b["title"] for b in blocks if req in b["reqs"]]
        decisions = [d["id"] for d in model.decisions if req in d["binds"]]
        rows.append([req, codes(linked), ", ".join(cards_) or "**нет блока**", codes(decisions) if decisions else "—"])
    research = sorted({b["rnd"] for b in blocks if b.get("rnd")})
    parts = ["Как читать: требование подтверждается историей с критериями, реализуется блоком и опирается на решение.",
             table(["Требование", "Истории", "Блоки", "Решения"], rows)]
    if research:
        parts += ["## Исследования компонента", "\n".join(f"- [[rnd:{name}|{name}]]" for name in research)]
    return "\n\n".join(parts)


def er_lines(tables):
    """ER-диаграмма: таблицы, ключи и связи по внешним ключам."""
    lines, known = ["erDiagram"], {t["title"].removeprefix("Таблица ") for t in tables}
    safe = lambda value: re.sub(r"\W", "_", str(value))
    for unit in tables:
        name = unit["title"].removeprefix("Таблица ")
        lines.append(f"  {safe(name)} {{")
        for item in unit.get("attributes", [])[:10]:
            mark = " PK" if item.get("pk") else " FK" if item.get("fk") else ""
            lines.append(f"    {safe(item['type']) or 'text'} {safe(item['name'])}{mark}")
        lines.append("  }")
    for unit in tables:
        for item in unit.get("attributes", []):
            if item.get("fk") in known:
                lines.append(f'  {safe(item["fk"])} ||--o{{ {safe(unit["title"].removeprefix("Таблица "))} : "{safe(item["name"])}"')
    return lines


def flow_lines(model, flows):
    lines = ["graph LR"]
    used = {end for unit in flows for end in (unit["from"], unit["to"])}
    for key in sorted(used):
        style = "comp" if key in model.components else "self" if key in model.systems and model.systems[key]["kind"] == "own" else "ext"
        lines.append(f'  {node(key)}["{label(model.title(key))}"]:::{style}')
    edges = collections.defaultdict(list)
    for unit in flows:
        edges[(unit["from"], unit["to"])] += unit["objects"]
    for (a, b), objects in sorted(edges.items()):
        names_ = list(dict.fromkeys(objects))
        text = ", ".join(names_[:3]) + (f" и ещё {len(names_) - 3}" if len(names_) > 3 else "")
        lines.append(f'  {node(a)} -->|"{label(text, 40)}"| {node(b)}')
    return lines


def tables_of(model, key=None):
    stores = [s for s in model.stores.values() if key is None or s["owner"] == key]
    wanted = {obj for s in stores for obj in s["objects"]}
    return [u for k, u in model.data.items() if k in wanted and u["class"] != "contract"]


def datamodel_view(model, key):
    parts = []
    tables = tables_of(model, key)
    if tables:
        parts += ["## Модель данных", diagram(er_lines(tables))]
    flows = [u for u in model.flows.values() if key in (u["from"], u["to"])]
    if flows:
        parts += ["## Потоки данных", diagram(flow_lines(model, flows)),
                  table(["Что движется", "Откуда", "Куда", "Канал"], [[u["title"], comp(model, u["from"]), comp(model, u["to"]), u.get("over", "")] for u in flows])]
    stores = [s for s in model.stores.values() if s["owner"] == key]
    if stores:
        parts += ["## Хранилища", table(["Хранилище", "Таблиц", "Резервирование"], [[s["title"], len(s["tables"]), s["backup"]] for s in stores])]
    return "\n\n".join(parts) or "Собственных данных у компонента нет."


def er_all(model):
    groups = [(s["title"], [u for k, u in model.data.items() if k in s["objects"]]) for s in model.stores.values() if s["objects"]]
    parts = ["ER-диаграммы по хранилищам. Связи построены по внешним ключам таблиц."]
    for title, tables in groups:
        parts += [f"## {title}", diagram(er_lines(tables))]
    return "\n\n".join(parts)


def dfd(model):
    flows = list(model.flows.values())
    return "\n\n".join(["Что движется между компонентами и системами.", diagram(flow_lines(model, flows)), table(
        ["Что движется", "Откуда", "Куда", "Тип", "Канал"], [[u["title"], comp(model, u["from"]), comp(model, u["to"]), u["flow_type"], u.get("over", "")] for u in flows])])


def type_view(model, key):
    unit = model.data[key]
    flows = [u for u in model.flows.values() if key in u["objects"]]
    parts = [f":::info\n{unit['title']}\n:::"]
    source = unit.get("source") or {}
    kinds = {"fork": "✅ контракт форка ICPlan", "ext": "📘 внешняя спецификация", "ours": "🧩 наш контракт"}
    if source:
        parts.append(f"**Источник:** {kinds.get(source.get('kind'), source.get('kind', ''))}: {source.get('ref', '')}")
    parents = [k for k, u in model.data.items() if k != key and u["class"] == "contract" and any(re.search(rf"\b{re.escape(key)}\b", a["type"]) for a in u.get("attributes", []))]
    if parents:
        parts.append("**Вложен в:** " + " ".join(f"`{item}`" for item in parents))
    if unit.get("attributes"):
        parts += ["## Поля", table(["Поле", "Тип", "Обязательное", "Описание"], [[f"`{a['name']}`", f"`{a['type']}`", "да" if a.get("required") else "", a.get("note", "")] for a in unit["attributes"]])]
    if source.get("why"):
        parts.append(f"**Почему так.** {source['why']}")
    if flows:
        parts += ["## Где передаётся", table(["Поток", "Откуда", "Куда", "Канал"], [[u["title"], comp(model, u["from"]), comp(model, u["to"]), u.get("over", "")] for u in flows])]
    return "\n\n".join(parts)


def types_index(model):
    rows = [[f"[[type:{key}|{key}]]", unit["title"], len(unit.get("attributes", []))] for key, unit in model.data.items() if unit["class"] == "contract"]
    return "Контракты данных между компонентами. Таблицы описаны на страницах «Данные и потоки» своих компонентов.\n\n" + table(["Тип", "Назначение", "Полей"], rows)


def sequences_view(model, key):
    items = [s for s in model.sequences if s.get("component") == key]
    return "\n\n".join(f"## {s['title']}\n\n```mermaid\n{s['diagram']}\n```" for s in items) or "Сценариев пока нет."


def sequences_all(model):
    return "\n\n".join(f"## {s['title']}\n\n```mermaid\n{s['diagram']}\n```" for s in model.sequences) or "Сценариев пока нет."


def decisions_view(model):
    parts = []
    for item in model.decisions:
        parts.append(f"## {item['id']}. {item['title']}\n\n**Правило:** {item['rule']}\n\n**Защищает от:** {item['prevents']}\n\n**Требования:** {codes(item['binds'])}")
    return "\n\n".join(parts)


def how_it_works(model):
    parts = ["Каждый процесс показан схемой по участникам и таблицей шагов."]
    for unit in model.processes.values():
        rows = [[i, s["title"], model.title(s["actor"]), model.title(s["function"]) if s.get("function") else "", names(model, s["inputs"]) if s["inputs"] else "", names(model, s["outputs"]) if s["outputs"] else ""]
                for i, s in enumerate(unit["steps"], 1)]
        parts += [f"## {unit['title']}", f"Запуск: {unit['trigger']}. Пути: {codes(unit.get('journeys', []))}.", process_diagram(model, unit),
                  table(["№", "Шаг", "Кто", "Функция", "Вход", "Выход"], rows)]
    return "\n\n".join(parts)


def data_view(model):
    rows = []
    for key, unit in model.data.items():
        stores = [s["title"] for s in model.stores.values() if key in s["objects"]]
        readers = sum(key in f["reads"] for f in model.functions.values())
        writers = sum(key in f["writes"] for f in model.functions.values())
        rows.append([unit["title"], unit["class"], unit["sensitivity"], ", ".join(stores) or "—", writers, readers])
    return "Сколько функций пишет и читает каждый объект данных.\n\n" + table(["Объект", "Класс", "Чувствительность", "Хранилище", "Пишут", "Читают"], rows)


def registers(model):
    decided = {True: "да", False: "нет", None: "не решено"}
    parts = ["## Решения", table(["Код", "Решение", "Правило"], [[d["id"], d["title"], d["rule"]] for d in model.decisions])]
    parts += ["## Интеграции", table(["Код", "Откуда и куда", "Тип", "Протокол", "Таймаут", "Повтор", "Идемпотентность"], [
        [k, f"{comp(model, u['from'])} → {comp(model, u['to'])}", u["integration_type"], u["protocol"], u["timeout"], u["retry"], decided[u["idempotent"]]]
        for k, u in model.integrations.items()])]
    parts += ["## Потоки данных", table(["Код", "Что движется", "Откуда и куда", "Тип", "Канал"], [
        [k, u["title"], f"{comp(model, u['from'])} → {comp(model, u['to'])}", u["flow_type"], u.get("over", "")] for k, u in model.flows.items()])]
    parts += ["## Хранилища", table(["Код", "Хранилище", "Владелец", "Таблиц", "Резервирование"], [
        [k, u["title"], comp(model, u["owner"]), len(u["tables"]), u["backup"]] for k, u in model.stores.items()])]
    parts += ["## Параметры", table(["Имя", "По умолчанию", "Мин", "Макс", "Почему"], [[f"`{p['name']}`", p["default"], p["min"], p["max"], p["why"]] for p in model.file("params.yaml", "params")])]
    parts += ["## Режимы отказа", table(["Объект", "Отказ", "Поведение", "Восстановление"], [
        [model.title(r["target"]), r["failure"], r["behavior"], r["recovery"]] for r in model.file("fmea.yaml", "rows")])]
    parts += ["## Сценарии качества", table(["Код", "NFR", "Стимул", "Мера", "Проверка"], [
        [q["id"], q["nfr"], q["stimulus"], q["response_measure"], q["fitness"]] for q in model.file("quality.yaml", "scenarios")])]
    return "\n\n".join(parts)


def coverage(model):
    epics = model.root / "_bmad-output" / "planning-artifacts" / "epics.md"
    pairs = re.findall(r"^\| (FR-\d+) \| (\d+\.\d+) \|", epics.read_text(encoding="utf-8"), re.M) if epics.exists() else []
    stories = collections.defaultdict(list)
    for req, story in pairs:
        stories[req].append(story)
    rows = []
    for req, items in stories.items():
        functions = [u["title"] for u in model.functions.values() if req in u["reqs"]]
        rows.append([req, ", ".join(items), "; ".join(functions[:3]) or "**нет**"])
    return "Какие истории и функции закрывают требование. **нет** показывает разрыв.\n\n" + table(["Требование", "Истории", "Функции"], rows)


def shape(problem):
    """Группирует одинаковые замечания: коды и имена в тексте заменяются многоточием."""
    text = re.sub(r"\b(?:FR|NFR|AD|US)-[\w-]+|\b[IS]\d+\b|`[^`]*`|«[^»]*»", "…", problem)
    return re.sub(r"(Объект|Нет таблицы|Нет: \S+(?: \S+)?|Нет интеграции|списке технологий:) .*", r"\1 …", text)[:90]


def readiness(model):
    report = model.report
    if not report:
        return "Сначала запустите `check.py`."
    state = report.get("readiness", {})
    head = [["Готовность", f"{state.get('score', '?')} из 100, {state.get('status', '?')}"], ["Блокеров", report["blockers"]], ["Предупреждений", report["warnings"]]]
    parts = [table(["Показатель", "Значение"], head)]
    if state.get("parts"):
        parts += ["## Из чего сложилось", table(["Часть", "Баллы"], state["parts"].items())]
    groups = collections.defaultdict(list)
    for item in report["findings"]:
        groups[(item["level"], item["gate"], shape(item["problem"]))].append(item)
    rows = [[{"blocker": "блокер", "warning": "замечание"}[level], gate, text, len(items), "; ".join(str(i["where"]) for i in items[:EXAMPLES])]
            for (level, gate, text), items in sorted(groups.items(), key=lambda p: (p[0][0], -len(p[1])))]
    if rows:
        parts += ["## Что мешает", "Одинаковые замечания собраны в одну строку. Полный список лежит в `_quality/check-report.yaml`.",
                  table(["Уровень", "Проверка", "Что не так", "Сколько", "Примеры"], rows)]
    return "\n\n".join(parts)


VIEWS = {"home": home, "component": component_view, "trace": trace_view, "datamodel": datamodel_view, "er": er_all, "dfd": dfd, "sequences": sequences_view,
         "seqall": sequences_all, "integrations": integrations_view, "spec": spec_view, "type": type_view, "types": types_index, "decisions": decisions_view, "c1": c1, "c2": c2, "c3": c3, "cards": cards, "stories": stories_view, "how": how_it_works, "data": data_view, "registers": registers, "coverage": coverage, "readiness": readiness}


def render(name, title, root):
    """Имя вида может нести аргумент: stories:agent-runner."""
    view, _, argument = name.partition(":")
    model = Model(root)
    body = VIEWS[view](model, argument) if argument else VIEWS[view](model)
    return f"# {title}\n\n> Страница собрана из файлов проекта, правьте источник.\n\n{body}\n"
