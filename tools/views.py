"""Страницы для человека: собираются из YAML и отчёта проверок, вручную не ведутся."""
import collections
import re

import yaml

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
            folder = self.arch / name
            setattr(self, name, {u["id"]: u for u in map(load_yaml, sorted(folder.glob("*.yaml")))} if folder.exists() else {})
        blocks = self.arch / "blocks"
        self.blocks = [(p.parent.name, load_yaml(p)) for p in sorted(blocks.rglob("*.yaml"))] if blocks.exists() else []
        decisions = self.arch / "decisions"
        self.decisions = [load_yaml(decisions / f"{d}.yaml") for d in load_yaml(decisions / "_order.yaml")["order"]] if decisions.exists() else []
        report = root / "_quality" / "check-report.yaml"
        self.report = load_yaml(report) if report.exists() else {}

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
    return ", ".join(f"`{item}`" for item in items) or "нет"


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
              ("Задачи", codes(block.get("tasks", []))), ("При сбое", block["on_failure"]), ("Почему так", block.get("why", ""))]
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
    folder = model.arch / "stories"
    stories = [load_yaml(path) for path in folder.glob("*.yaml")] if folder.exists() else []
    return sorted(stories, key=lambda s: [int(part) for part in s["number"].split(".")])


def story_card(story, blocks):
    """Карточка истории: выноска с ролью, целью и критериями."""
    criteria = "\n".join(f"- [ ] {item}" for item in story["accept"])
    goal = f"**Хочу:** {story['want']}" + (f"\n\n**Чтобы:** {story['so_that']}" if story.get("so_that") else "")
    links = [f"**Требования:** {codes(story['reqs'])}"]
    if blocks:
        links.append(f"**Блоки:** {', '.join(blocks)}")
    head = f"### {story.get('source', story['id'])} · история {story['number']}"
    return f"{head}\n\n:::info\n**{story['role']}**\n\n{goal}\n:::\n\n{criteria}\n\n{' · '.join(links)}"


def stories_view(model, component):
    parts = []
    processes = [u for u in model.processes.values() if u.get("component") == component]
    for number, unit in enumerate(processes, 1):
        parts += [f"## Процесс {number}. {unit['title']}", f"Покрывает истории: {codes(unit.get('stories', []))}", process_diagram(model, unit), LEGEND]
    stories = [s for s in load_stories(model) if s["component"] == component]
    by_story = collections.defaultdict(list)
    for owner, block in model.blocks:
        for number in block.get("stories", []):
            by_story[number].append(block["title"])
    if stories:
        parts += ["## Сводка", table(["История", "Роль", "Что хочет", "Критериев"], [[s.get("source", s["id"]), s["role"], s["want"], len(s["accept"])] for s in stories]), "## Истории"]
        parts += [story_card(s, by_story[s["number"]]) for s in stories]
    return "\n\n".join(parts) or "Историй пока нет."


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
        [k, f"{model.title(u['from'])} → {model.title(u['to'])}", u["integration_type"], u["protocol"], u["timeout"], u["retry"], decided[u["idempotent"]]]
        for k, u in model.integrations.items()])]
    parts += ["## Потоки данных", table(["Код", "Что движется", "Откуда и куда", "Тип", "Канал"], [
        [k, u["title"], f"{model.title(u['from'])} → {model.title(u['to'])}", u["flow_type"], u.get("over", "")] for k, u in model.flows.items()])]
    parts += ["## Хранилища", table(["Код", "Хранилище", "Владелец", "Таблиц", "Резервирование"], [
        [k, u["title"], model.title(u["owner"]), len(u["tables"]), u["backup"]] for k, u in model.stores.items()])]
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


VIEWS = {"c1": c1, "c2": c2, "c3": c3, "cards": cards, "stories": stories_view, "how": how_it_works, "data": data_view, "registers": registers, "coverage": coverage, "readiness": readiness}


def render(name, title, root):
    """Имя вида может нести аргумент: stories:agent-runner."""
    view, _, argument = name.partition(":")
    model = Model(root)
    body = VIEWS[view](model, argument) if argument else VIEWS[view](model)
    return f"# {title}\n\n> Страница собрана из файлов проекта, правьте источник.\n\n{body}\n"
