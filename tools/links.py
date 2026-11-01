"""Ссылки между страницами: относительные пути документов, метки видов и коды в тексте."""
import pathlib
import re

CODE = re.compile(r"(?<![\w/#-])(NFR-\d+|FR-\d+|AD-\d+|US-[A-Z]+-\d+|I\d{1,2})(?![\w-])")
PROTECTED = re.compile(r"(```.*?```|`[^`\n]*`|!?\[[^\]]*\]\([^)]*\)|\{\{svg:[^}]*\}\}|^#{1,6} [^\n]*$)", re.S | re.M)
MARK = re.compile(r"\[\[([^\]|]+)\|([^\]]+)\]\]")


class Links:
    def __init__(self, space, created, root, model):
        self.base = f"/s/{space}/p/"
        self.root = root
        self.by_key = {item["key"]: slug for item, _, slug in created if item.get("key")}
        self.by_source = {item["source"]: slug for item, _, slug in created if item.get("source")}
        self.codes = {**model.term_pages(), **model.code_pages()}
        names = sorted(model.term_pages(), key=len, reverse=True)
        self.terms = re.compile(r"(?<![\w/#-])(" + "|".join(re.escape(name) for name in names) + r")(?![\w-])") if names else None

    def url(self, key):
        slug = self.by_key.get(key)
        return self.base + slug if slug else None

    def mark(self, match):
        url = self.url(match.group(1))
        return f"[{match.group(2)}]({url})" if url else match.group(2)

    def path_link(self, match, source):
        """Относительный путь документа становится адресом страницы, неопубликованный остаётся текстом."""
        text, target = match.group(1), match.group(2).split("#")[0]
        folder = pathlib.PurePosixPath(source).parent
        parts = []
        for part in (folder / target).parts:
            if part == ".." and parts:
                parts.pop()
            elif part != ".":
                parts.append(part)
        slug = self.by_source.get("/".join(parts))
        return f"[{text}]({self.base}{slug})" if slug else text

    def code(self, match, own=None):
        key = self.codes.get(match.group(1), "")
        url = self.url(key) if key != own else None
        return f"[{match.group(1)}]({url})" if url else match.group(1)

    def plain(self, text, own):
        """Обычный текст: сначала коды, затем имена компонентов, типов и таблиц."""
        pieces = re.split(r"(\[[^\]]*\]\([^)]*\))", CODE.sub(lambda m: self.code(m, own), text))
        if self.terms:
            pieces = [piece if index % 2 else self.terms.sub(lambda m: self.code(m, own), piece) for index, piece in enumerate(pieces)]
        return "".join(pieces)

    def inline(self, piece, own):
        """Код в обратных кавычках тоже становится ссылкой, если это имя с собственной страницей."""
        if piece.startswith("`") and not piece.startswith("```"):
            url = self.url(self.codes.get(piece.strip("`"), ""))
            if url and self.codes.get(piece.strip("`")) != own:
                return f"[{piece}]({url})"
        return piece

    def apply(self, text, item):
        text = MARK.sub(self.mark, text)
        if item.get("source"):
            text = re.sub(r"(?<!!)\[([^\]]+)\]\((?!https?:|/|#|mailto:)([^)\s]+\.md(?:#[^)]*)?)\)", lambda m: self.path_link(m, item["source"]), text)
        pieces = PROTECTED.split(text)
        own = item.get("key")
        return "".join(self.inline(piece, own) if index % 2 else self.plain(piece, own) for index, piece in enumerate(pieces))
