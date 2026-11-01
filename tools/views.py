"""Страницы для человека: собираются из YAML и отчёта проверок, вручную не ведутся."""
import re

import yaml

FOLDERS = ("actors", "processes", "services", "systems", "functions", "components", "data", "stores", "flows", "integrations", "nodes")


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
        self.blocks = [load_yaml(p) for p in sorted(blocks.rglob("*.yaml"))] if blocks.exists() else []
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
    return re.sub(r"\W", "_", key)


def table(header, rows):
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(str(cell).replace("|", "/").replace("\n", " ") for cell in row) + " |" for row in rows]
    return "\n".join(lines)


def codes(items):
    return ", ".join(f"`{item}`" for item in items) or "нет"


def c1(model):
    lines = ["Кто пользуется системой и с какими внешними системами она связана.", "", "```mermaid", "graph LR"]
    for key, unit in model.actors.items():
        lines.append(f'  {node(key)}(["{unit["title"]}"])')
    for key, unit in model.systems.items():
        lines.append(f'  {node(key)}["{unit["title"]}"]')
    edges = set()
    for unit in model.flows.values():
        edges.add((model.system_of(unit["from"]), model.system_of(unit["to"]), unit["title"]))
    lines += [f'  {node(a)} -->|{label}| {node(b)}' for a, b, label in sorted(edges) if a != b]
    consumers = {(c, s["provider"]) for s in model.services.values() for c in s["consumers"] if c in model.actors}
    lines += [f"  {node(c)} --> {node(p)}" for c, p in sorted(consumers)]
    return "\n".join(lines + ["```", "", "## Сервисы", "", table(
        ["Сервис", "Потребители", "Обязательства"],
        [[s["title"], codes(s["consumers"]), "; ".join(o["text"] for o in s["objectives"])] for s in model.services.values()])])


def c2(model):
    lines = ["Контейнеры, хранилища и каналы между ними.", "", "```mermaid", "graph LR"]
    for key, unit in model.components.items():
        lines.append(f'  {node(key)}["{unit["title"]}<br/>{unit.get("tech", "")}"]')
    for key, unit in model.stores.items():
        lines.append(f'  {node(key)}[("{unit["title"]}")]')
        lines.append(f"  {node(unit['owner'])} --> {node(key)}")
    for key, unit in model.integrations.items():
        lines.append(f'  {node(unit["from"])} -->|"{key}"| {node(unit["to"])}')
    return "\n".join(lines + ["```", "", "## Компоненты", "", table(
        ["Компонент", "Отвечает за", "Технология", "Блоки"],
        [[u["title"], u["responsibility"], u.get("tech", ""), sum(b["id"].startswith(k + "-") for b in model.blocks)] for k, u in model.components.items()])])


def c3(model):
    fill = model.report.get("coverage", {}).get("blocks", {})
    rows = [[b["id"], b["title"], b["kind"], codes(b["reqs"]), f"{fill.get(b['id'], {}).get('filled', '?')} %"] for b in model.blocks]
    return "Блоки внутри компонентов. Карточка отвечает на вопросы исполнителя.\n\n" + table(["Блок", "Название", "Вид", "Требования", "Заполнено"], rows)


def card(block):
    data = block["data"] if isinstance(block["data"], str) else ", ".join(f"{row['table']} ({row['access']})" for row in block["data"])
    params = block["params"] if isinstance(block["params"], str) else codes(block["params"])
    io = "; ".join(f"{'←' if item['dir'] == 'in' else '→'} {item['with']}: {item['what']}" for item in block["io"])
    fields = [("Что делает", "; ".join(block["does"])), ("Технология", block.get("tech", "")), ("Истории", codes(block.get("stories", []))),
              ("Входы и выходы", io), ("Данные", data), ("Параметры", params), ("Требования", codes(block["reqs"])),
              ("Задачи", codes(block.get("tasks", []))), ("При сбое", block["on_failure"]), ("Почему так", block.get("why", ""))]
    return f"## {block['title']}\n\n" + table(["Поле", "Значение"], fields)


def cards(model):
    return "\n\n".join(card(block) for block in model.blocks) or "Карточек пока нет."


def how_it_works(model):
    parts = ["Каждый процесс показан по шагам: кто действует, какая функция работает, что входит и что выходит."]
    for unit in model.processes.values():
        rows = [[i, s["title"], model.title(s["actor"]), model.title(s.get("function", "—")), codes(s["inputs"]), codes(s["outputs"])] for i, s in enumerate(unit["steps"], 1)]
        parts += [f"## {unit['title']}", f"Запуск: {unit['trigger']}. Пути: {codes(unit.get('journeys', []))}.",
                  table(["№", "Шаг", "Кто", "Функция", "Вход", "Выход"], rows)]
    return "\n\n".join(parts)


def data_view(model):
    rows = []
    for key, unit in model.data.items():
        stores = [s["title"] for s in model.stores.values() if key in s["objects"]]
        readers = [f["title"] for f in model.functions.values() if key in f["reads"]]
        writers = [f["title"] for f in model.functions.values() if key in f["writes"]]
        rows.append([unit["title"], unit["class"], unit["sensitivity"], ", ".join(stores) or "нет", ", ".join(writers) or "нет", ", ".join(readers) or "нет"])
    return "Кто пишет и кто читает каждый объект данных.\n\n" + table(["Объект", "Класс", "Чувствительность", "Хранилище", "Пишут", "Читают"], rows)


def registers(model):
    parts = ["## Решения", table(["Код", "Решение", "Правило", "Требования"], [[d["id"], d["title"], d["rule"], ", ".join(d["binds"])] for d in model.decisions])]
    parts += ["## Интеграции", table(["Код", "От", "К", "Тип", "Протокол", "Вход", "Таймаут", "Повтор", "Идемпотентность"], [
        [k, u["from"], u["to"], u["integration_type"], u["protocol"], u["auth"], u["timeout"], u["retry"], {True: "да", False: "нет", None: "не решено"}[u["idempotent"]]]
        for k, u in model.integrations.items()])]
    parts += ["## Потоки данных", table(["Код", "Что", "От", "К", "Событие", "Тип", "Канал"], [
        [k, u["title"], u["from"], u["to"], u["trigger"], u["flow_type"], u.get("over", "")] for k, u in model.flows.items()])]
    parts += ["## Параметры", table(["Имя", "По умолчанию", "Мин", "Макс", "Почему"], [[p["name"], p["default"], p["min"], p["max"], p["why"]] for p in model.file("params.yaml", "params")])]
    parts += ["## Режимы отказа", table(["Объект", "Отказ", "Обнаружение", "Поведение", "Восстановление"], [
        [r["target"], r["failure"], r["detection"], r["behavior"], r["recovery"]] for r in model.file("fmea.yaml", "rows")])]
    parts += ["## Сценарии качества", table(["Код", "NFR", "Стимул", "Отклик", "Мера", "Проверка"], [
        [q["id"], q["nfr"], q["stimulus"], q["response"], q["response_measure"], q["fitness"]] for q in model.file("quality.yaml", "scenarios")])]
    return "\n\n".join(parts)


def coverage(model):
    data = model.report.get("coverage", {})
    guessed = data.get("scenario_classes", {}).get("epics_guessed", {})
    epics = model.root / "_bmad-output" / "planning-artifacts" / "epics.md"
    pairs = re.findall(r"^\| (FR-\d+) \| (\d+\.\d+) \|", epics.read_text(encoding="utf-8"), re.M) if epics.exists() else []
    rows = []
    for req, story in pairs:
        functions = [u["title"] for u in model.functions.values() if req in u["reqs"]]
        rows.append([req, story, ", ".join(functions) or "**нет**", ", ".join(guessed.get(story, [])) or "**нет**"])
    return "Пустая клетка показывает разрыв. Классы в этой таблице угаданы по словам, это подсказка.\n\n" + table(["Требование", "История", "Функции", "Классы S1–S12"], rows)


def readiness(model):
    report = model.report
    if not report:
        return "Сначала запустите `check.py`."
    state = report.get("readiness", {})
    head = [["Готовность", f"{state.get('score', '?')} из 100, {state.get('status', '?')}"], ["Блокеров", report["blockers"]], ["Предупреждений", report["warnings"]]]
    parts = [table(["Показатель", "Значение"], head)]
    if state.get("parts"):
        parts += ["## Из чего сложилось", table(["Часть", "Баллы"], state["parts"].items())]
    if report["findings"]:
        parts += ["## Замечания", table(["Уровень", "Проверка", "Где", "Что"], [[f["level"], f["gate"], f["where"], f["problem"]] for f in report["findings"]])]
    return "\n\n".join(parts)


VIEWS = {"c1": c1, "c2": c2, "c3": c3, "cards": cards, "how": how_it_works, "data": data_view, "registers": registers, "coverage": coverage, "readiness": readiness}


def render(name, title, root):
    return f"# {title}\n\n> Страница собрана из файлов проекта, правьте источник.\n\n{VIEWS[name](Model(root))}\n"
