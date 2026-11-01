#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6"]
# ///
"""Публикует документацию проекта в Docmost по файлу docmost.yaml.

Запуск: uv run publish.py --root <проект>
Источник правды — файлы проекта: повторный запуск заменяет все страницы пространства.
"""
import argparse
import http.cookiejar
import json
import os
import pathlib
import re
import sys
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


def page_text(item, root):
    if item.get("view"):
        return render(item["view"], item["title"], root)
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


def create_tree(client, space_id, items, parent, created):
    """Первый проход: пустые страницы нужной иерархии, чтобы у всех появились адреса."""
    for index, item in enumerate(items):
        page_id = client.import_page(space_id, f"# {item['title']}\n")
        client.post("/api/pages/move", {"pageId": page_id, "parentPageId": parent, "position": f"a{index:04d}"})
        slug = client.post("/api/pages/info", {"pageId": page_id})["data"]["slugId"]
        created.append((item, page_id, slug))
        create_tree(client, space_id, item.get("children", []), page_id, created)


def attach_images(client, page_id, content, root, model):
    """Заменяет метки схем картинками: SVG строится скриптом и загружается на страницу."""
    def replace(match):
        name = f"{re.sub(r'[^A-Za-z0-9-]', '-', match.group(1))}.svg"
        link = client.upload(page_id, name, svg_for(match.group(1), model).encode("utf-8"))
        return f"![схема]({link})"
    return re.sub(r"\{\{svg:([^}]+)\}\}", replace, content)


def fill_tree(client, created, root, links, model, errors):
    """Второй проход: содержимое со ссылками на уже известные адреса."""
    for item, page_id, _ in created:
        text = re.sub(r"\{\{seq:([^}]+)\}\}", lambda m: model.sequence_block(m.group(1)), page_text(item, root))
        if item.get("component"):
            text = re.sub(r"^(# .*\n)", lambda m: f"{m.group(1)}\n{tab_bar(item['component'], item.get('key'))}\n", text, count=1)
        content = attach_images(client, page_id, links.apply(text, item), root, model)
        body = re.sub(r"^# .*\n+", "", content, count=1)
        client.post("/api/pages/update", {"pageId": page_id, "content": body, "format": "markdown", "operation": "replace"})
        saved = client.post("/api/pages/info", {"pageId": page_id, "format": "markdown"})["data"]["content"]
        if body.count("```mermaid") != saved.count("```mermaid"):
            errors.append(f"{item['title']}: схем было {body.count('```mermaid')}, стало {saved.count('```mermaid')}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".", type=pathlib.Path)
    args = parser.parse_args()
    root = args.root.resolve()
    config = yaml.safe_load((root / "docmost.yaml").read_text(encoding="utf-8"))
    client = Docmost(config["url"].rstrip("/"))
    email, password = credentials(config, root)
    client.post("/api/auth/login", {"email": email, "password": password})

    spaces = client.post("/api/spaces", {"limit": 100})["data"]["items"]
    space = next((s for s in spaces if s["slug"] == config["space"]["slug"]), None)
    if space is None:
        space = client.post("/api/spaces/create", config["space"])["data"]
    space_id = space["id"]

    for page in client.post("/api/pages/sidebar-pages", {"spaceId": space_id, "limit": 100})["data"]["items"]:
        client.post("/api/pages/delete", {"pageId": page["id"], "permanentlyDelete": True})

    errors, created = [], []
    create_tree(client, space_id, config["tree"], None, created)
    model = Model(root)
    links = Links(config["space"]["slug"], created, root, model)
    fill_tree(client, created, root, links, model, errors)
    count = len(created)

    print(f"Опубликовано страниц: {count}")
    print(f"Открыть: {config['url'].rstrip('/')}/s/{config['space']['slug']}")
    print("\n".join(errors) if errors else "Содержимое сохранилось")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
