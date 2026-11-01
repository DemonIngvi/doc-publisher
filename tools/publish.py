#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6"]
# ///
"""Публикует документацию проекта в Docmost по файлу docmost.yaml.

Запуск: uv run publish.py --root <проект>
Источник правды — файлы проекта. Обновляются только изменившиеся страницы, адреса страниц постоянны.
Ход работы пишется в _quality/publish-progress.json.
"""
import argparse
import hashlib
import http.cookiejar
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request
import uuid

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from links import Links  # noqa: E402
from views import Model, render, svg_for, tab_bar  # noqa: E402


class Docmost:
    def __init__(self, base):
        self.base = base
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def post(self, path, data=None, raw=None, ctype="application/json"):
        body = raw if raw is not None else json.dumps(data or {}).encode()
        request = urllib.request.Request(self.base + path, data=body, headers={"Content-Type": ctype}, method="POST")
        try:
            with self.opener.open(request, timeout=60) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            raise SystemExit(f"{path}: {error.code} {error.read()[:400]!r}")

    def import_page(self, space_id, content):
        boundary = uuid.uuid4().hex
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="spaceId"\r\n\r\n{space_id}\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="page.md"\r\n'
            "Content-Type: text/markdown\r\n\r\n"
        ).encode() + content.encode("utf-8") + f"\r\n--{boundary}--\r\n".encode()
        return self.post("/api/pages/import", raw=body, ctype=f"multipart/form-data; boundary={boundary}")["data"]["id"]


    def upload(self, page_id, name, content):
        """Загружает файл на страницу и возвращает его адрес для Markdown."""
        boundary = uuid.uuid4().hex
        kind = "image/svg+xml"
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="pageId"\r\n\r\n{page_id}\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\nContent-Type: {kind}\r\n\r\n'
        ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
        saved = self.post("/api/files/upload", raw=body, ctype=f"multipart/form-data; boundary={boundary}")
        return f"/api/files/{saved['id']}/{saved['fileName']}"


def credentials(config, root):
    if os.environ.get("DOCMOST_EMAIL"):
        return os.environ["DOCMOST_EMAIL"], os.environ["DOCMOST_PASSWORD"]
    path = (root / config["credentials"]).resolve()
    values = dict(line.split(": ", 1) for line in path.read_text(encoding="utf-8").splitlines())
    return values["email"], values["password"]


def page_text(item, root, model=None):
    if item.get("view"):
        return render(item["view"], item["title"], root, model)
    return prepare(item["title"], item.get("source"), root, item.get("note"))


def prepare(title, source, root, note):
    if source is None:
        return f"# {title}\n\nДокументы этого раздела находятся на вложенных страницах.\n"
    text = (root / source).read_text(encoding="utf-8")
    if source.endswith((".yaml", ".yml")):
        comment = f"> {note}\n\n" if note else ""
        return f"# {title}\n\n{comment}```yaml\n{text}\n```\n"
    meta = ""
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if match:
        meta = f"\n\n## Метаданные документа\n\n```yaml\n{match.group(1)}\n```\n"
        text = text[match.end():]
    text = re.sub(r"<!--.*?-->\n?", "", text, flags=re.S)
    text = re.sub(r"</?frozen-after-approval[^>]*>\n?", "", text)
    text = re.sub(r"^\s*# .*\n", "", text, count=1)
    return f"# {title}\n\n{text.strip()}\n{meta}"


def used_views(items):
    for item in items:
        if item.get("view"):
            yield item["view"].split(":")[0]
        yield from used_views(item.get("children", []))


def check_catalog(tree, root):
    """Вид без описания в каталоге не публикуется: страница должна иметь основание в документации."""
    path = root / "docs" / "views.yaml"
    known = set(yaml.safe_load(path.read_text(encoding="utf-8"))["views"]) if path.exists() else set()
    missing = sorted(set(used_views(tree)) - known)
    if missing:
        raise SystemExit(f"Нет в docs/views.yaml: {', '.join(missing)}")


def sync_tree(client, space_id, items, parent, state, prefix, created):
    """Находит страницы дерева или создаёт недостающие. Адрес существующей страницы не меняется."""
    existing = None
    for index, item in enumerate(items):
        ident = f"{prefix}/{item['title']}"
        entry = state.get(ident)
        if not entry:
            if existing is None:
                request = {"spaceId": space_id, "limit": 100, **({"pageId": parent} if parent else {})}
                existing = {p["title"]: p for p in client.post("/api/pages/sidebar-pages", request)["data"]["items"]}
            found = existing.get(item["title"])
            if found:
                entry = {"id": found["id"], "slug": found["slugId"], "hash": ""}
            else:
                page_id = client.import_page(space_id, f"# {item['title']}\n")
                client.post("/api/pages/move", {"pageId": page_id, "parentPageId": parent, "position": f"a{index:04d}"})
                entry = {"id": page_id, "slug": client.post("/api/pages/info", {"pageId": page_id})["data"]["slugId"], "hash": ""}
            state[ident] = entry
        created.append((item, entry["id"], entry["slug"], ident))
        sync_tree(client, space_id, item.get("children", []), entry["id"], state, ident, created)


def attach_images(client, page_id, content, model):
    """Заменяет метки схем картинками: SVG строится скриптом и загружается на страницу."""
    def replace(match):
        name = f"{re.sub(r'[^A-Za-z0-9-]', '-', match.group(1))}.svg"
        link = client.upload(page_id, name, svg_for(match.group(1), model).encode("utf-8"))
        return f"![схема]({link})"
    return re.sub(r"\{\{svg:([^}]+)\}\}", replace, content)


def page_hash(content, model):
    """Отпечаток страницы вместе с её схемами: схема меняется и без правки текста."""
    digest = hashlib.sha256(content.encode("utf-8"))
    for name in re.findall(r"\{\{svg:([^}]+)\}\}", content):
        digest.update(svg_for(name, model).encode("utf-8"))
    return digest.hexdigest()


class Progress:
    """Файл состояния публикации: его читает интерфейс, чтобы показать ход и оставшееся время."""

    def __init__(self, path, total):
        self.path, self.total, self.started = path, total, time.time()
        self.changed, self.done = 0, 0
        self.path.parent.mkdir(exist_ok=True)

    def write(self, status, current=""):
        elapsed = time.time() - self.started
        left = round(elapsed / self.done * (self.changed - self.done)) if self.done else None
        self.path.write_text(json.dumps({"status": status, "total": self.total, "changed": self.changed, "done": self.done, "current": current,
                                         "elapsed_seconds": round(elapsed), "left_seconds": left}, ensure_ascii=False), encoding="utf-8")


def mention(entry, creator):
    return {"type": "mention", "attrs": {"id": uuid.uuid4().hex, "label": entry["title"], "entityType": "page", "entityId": entry["id"], "slugId": entry["slug"], "creatorId": creator}}


def to_mentions(node, pages, creator):
    """Ссылка с названием страницы становится упоминанием: обычная ссылка Docmost открывает окно, а не страницу."""
    changed = 0
    children = []
    for child in node.get("content", []):
        marks = [m for m in child.get("marks", []) if m["type"] == "link"]
        slug = marks[0]["attrs"]["href"].rsplit("/", 1)[-1] if marks else ""
        if child.get("type") == "text" and slug in pages and child["text"].strip() == pages[slug]["title"]:
            children.append(mention(pages[slug], creator))
            changed += 1
        else:
            changed += to_mentions(child, pages, creator)
            children.append(child)
    if "content" in node:
        node["content"] = children
    return changed


def build_page(item, root, links, model):
    text = re.sub(r"\{\{seq:([^}]+)\}\}", lambda m: model.sequence_block(m.group(1)), page_text(item, root, model))
    if item.get("component"):
        bar = tab_bar(item["component"], item.get("key"), links.by_key, model)
        text = re.sub(r"^(# .*\n)", lambda m: f"{m.group(1)}\n{bar}\n", text, count=1)
    return links.apply(text, item)


def update_page(client, page_id, content, pages, model, title, errors):
    body = re.sub(r"^# .*\n+", "", attach_images(client, page_id, content, model), count=1)
    client.post("/api/pages/update", {"pageId": page_id, "content": body, "format": "markdown", "operation": "replace"})
    saved = client.post("/api/pages/info", {"pageId": page_id, "format": "markdown"})["data"]["content"]
    if body.count("```mermaid") != saved.count("```mermaid"):
        errors.append(f"{title}: схем было {body.count('```mermaid')}, стало {saved.count('```mermaid')}")
    if "/s/" in saved:
        info = client.post("/api/pages/info", {"pageId": page_id, "format": "json"})["data"]
        if to_mentions(info["content"], pages, info["creatorId"]):
            client.post("/api/pages/update", {"pageId": page_id, "content": info["content"], "format": "json", "operation": "replace"})


def load_state(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".", type=pathlib.Path)
    parser.add_argument("--force", action="store_true", help="Обновить все страницы, даже без изменений")
    args = parser.parse_args()
    root = args.root.resolve()
    config = yaml.safe_load((root / "docmost.yaml").read_text(encoding="utf-8"))
    check_catalog(config["tree"], root)
    client = Docmost(os.environ.get("DOCMOST_URL") or config["url"].rstrip("/"))
    email, password = credentials(config, root)
    client.post("/api/auth/login", {"email": email, "password": password})

    spaces = client.post("/api/spaces", {"limit": 100})["data"]["items"]
    space = next((s for s in spaces if s["slug"] == config["space"]["slug"]), None)
    if space is None:
        space = client.post("/api/spaces/create", config["space"])["data"]

    state_path = root / ".doc-kit" / "docmost-state.json"
    state = load_state(state_path)
    progress = Progress(root / "_quality" / "publish-progress.json", 0)
    progress.write("подготовка")
    created, errors = [], []
    sync_tree(client, space["id"], config["tree"], None, state, "", created)
    live = {ident for *_, ident in created}
    for ident in sorted(set(state) - live, key=len, reverse=True):
        client.post("/api/pages/delete", {"pageId": state.pop(ident)["id"], "permanentlyDelete": True})
    model = Model(root)
    links = Links(config["space"]["slug"], [row[:3] for row in created], root, model)
    pages = {slug: {"id": page_id, "slug": slug, "title": item["title"]} for item, page_id, slug, _ in created}
    queue = []
    for item, page_id, _, ident in created:
        content = build_page(item, root, links, model)
        digest = page_hash(content, model)
        if args.force or state[ident].get("hash") != digest:
            queue.append((item, page_id, ident, content, digest))
    progress.total, progress.changed = len(created), len(queue)
    for item, page_id, ident, content, digest in queue:
        progress.write("публикация", item["title"])
        update_page(client, page_id, content, pages, model, item["title"], errors)
        state[ident]["hash"] = digest
        progress.done += 1
        state_path.parent.mkdir(exist_ok=True)
        state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    state_path.parent.mkdir(exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    progress.write("ошибка" if errors else "готово")
    print(f"Страниц: {len(created)}, обновлено: {len(queue)}, за {round(time.time() - progress.started)} с")
    print(f"Открыть: {config['url'].rstrip('/')}/s/{config['space']['slug']}")
    print("\n".join(errors) if errors else "Содержимое сохранилось")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
