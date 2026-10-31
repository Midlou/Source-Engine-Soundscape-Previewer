"""A KeyValues (VDF) parser/writer that keeps comments.

Soundscape and soundscript files are KeyValues text. Backslashes are NOT treated
as escapes because Valve's scripts use them as path separators.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field

_uid = itertools.count(1)


class KVParseError(Exception):
    def __init__(self, message: str, line: int):
        super().__init__(f"Line {line}: {message}")
        self.line = line


@dataclass(eq=False)
class KVNode:
    key: str
    value: str | None = None  # None means this node is a block
    children: list["KVNode"] | None = None
    comments: list[str] = field(default_factory=list)  # comment lines before the node
    trailing: str | None = None  # comment on the same line
    end_comments: list[str] = field(default_factory=list)  # comments before the closing brace
    condition: str | None = None  # e.g. [$WIN32]
    line: int = 0
    uid: int = field(default_factory=lambda: next(_uid))

    @property
    def is_block(self) -> bool:
        return self.children is not None

    def get(self, key: str, default: str | None = None) -> str | None:
        k = key.lower()
        for c in self.children or ():
            if c.key.lower() == k and not c.is_block:
                return c.value
        return default

    def find(self, key: str) -> "KVNode | None":
        k = key.lower()
        for c in self.children or ():
            if c.key.lower() == k:
                return c
        return None

    def find_all(self, key: str) -> list["KVNode"]:
        k = key.lower()
        return [c for c in self.children or () if c.key.lower() == k]

    def set(self, key: str, value: str | None) -> None:
        """Set a key/value child; value None removes it."""
        existing = self.find(key)
        if value is None:
            if existing is not None:
                self.children.remove(existing)
            return
        if existing is not None and not existing.is_block:
            existing.value = value
        else:
            self.children.append(KVNode(key, value))

    def clone(self) -> "KVNode":
        return KVNode(
            self.key,
            self.value,
            [c.clone() for c in self.children] if self.children is not None else None,
            list(self.comments),
            self.trailing,
            list(self.end_comments),
            self.condition,
            self.line,
        )


# ---------------------------------------------------------------- tokenizer

_STR, _OPEN, _CLOSE, _COMMENT, _COND = range(5)


def _tokenize(text: str):
    i, n, line = 0, len(text), 1
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            i += 1
        elif c in " \t\r﻿":
            i += 1
        elif c == "/" and text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            yield _COMMENT, text[i + 2 : j].rstrip("\r"), line
            i = j
        elif c == "{":
            yield _OPEN, c, line
            i += 1
        elif c == "}":
            yield _CLOSE, c, line
            i += 1
        elif c == '"':
            j = text.find('"', i + 1)
            if j < 0:
                raise KVParseError("Unterminated string", line)
            s = text[i + 1 : j]
            yield _STR, s, line
            line += s.count("\n")
            i = j + 1
        elif c == "[":
            j = text.find("]", i)
            if j < 0:
                raise KVParseError("Unterminated conditional", line)
            yield _COND, text[i : j + 1], line
            i = j + 1
        else:
            j = i
            while j < n and text[j] not in ' \t\r\n"{}':
                if text.startswith("//", j):
                    break
                j += 1
            yield _STR, text[i:j], line
            i = j


def parse_full(text: str) -> tuple[list[KVNode], list[str]]:
    """Parse KeyValues text into (top-level nodes, comments after the last node)."""
    tokens = list(_tokenize(text))
    pos = 0
    n = len(tokens)

    def parse_block(depth: int) -> tuple[list[KVNode], list[str]]:
        nonlocal pos
        nodes: list[KVNode] = []
        pending: list[str] = []
        last_line = -1
        while pos < n:
            kind, val, line = tokens[pos]
            if kind == _COMMENT:
                pos += 1
                if nodes and line == last_line and nodes[-1].trailing is None:
                    nodes[-1].trailing = val
                else:
                    pending.append(val)
                continue
            if kind == _CLOSE:
                if depth == 0:
                    raise KVParseError("Unexpected '}'", line)
                pos += 1
                return nodes, pending
            if kind == _OPEN:
                raise KVParseError("Unexpected '{' (missing key?)", line)
            if kind == _COND:
                pos += 1
                continue
            # key
            key = val
            pos += 1
            if key.startswith("#") and key.lower() in ("#include", "#base"):
                # directive: skip its argument
                if pos < n and tokens[pos][0] == _STR:
                    pos += 1
                continue
            node = KVNode(key, line=line, comments=pending)
            pending = []
            # skip comments between key and value
            while pos < n and tokens[pos][0] == _COMMENT:
                node.comments.append(tokens[pos][1])
                pos += 1
            if pos < n and tokens[pos][0] == _COND:
                node.condition = tokens[pos][1]
                pos += 1
            if pos >= n:
                raise KVParseError(f"Missing value for key '{key}'", line)
            kind, val, vline = tokens[pos]
            if kind == _STR:
                node.value = val
                pos += 1
                if pos < n and tokens[pos][0] == _COND:
                    node.condition = tokens[pos][1]
                    pos += 1
                last_line = vline
            elif kind == _OPEN:
                pos += 1
                node.children, node.end_comments = parse_block(depth + 1)
                last_line = tokens[pos - 1][2]
            else:
                raise KVParseError(f"Missing value for key '{key}'", line)
            nodes.append(node)
        if depth > 0:
            raise KVParseError("Missing '}' at end of file", tokens[-1][2] if tokens else 1)
        return nodes, pending

    return parse_block(0)


def parse(text: str) -> list[KVNode]:
    return parse_full(text)[0]


# ------------------------------------------------------------------- writer


def _quote(s: str) -> str:
    return '"' + s.replace('"', "'") + '"'


def dumps(nodes: list[KVNode], trailing_comments: list[str] | None = None) -> str:
    out: list[str] = []

    def comment_lines(comments: list[str], indent: str) -> None:
        for c in comments:
            out.append(f"{indent}//{c}")

    def write(node_list: list[KVNode], depth: int) -> None:
        indent = "\t" * depth
        # align values inside a block
        width = max((len(c.key) + 2 for c in node_list if not c.is_block), default=0)
        for idx, node in enumerate(node_list):
            comment_lines(node.comments, indent)
            cond = f" {node.condition}" if node.condition else ""
            tail = f"\t//{node.trailing}" if node.trailing is not None else ""
            if node.is_block:
                if depth == 0 and idx > 0 and not node.comments:
                    out.append("")
                out.append(f"{indent}{_quote(node.key)}{cond}{tail}")
                out.append(f"{indent}{{")
                write(node.children, depth + 1)
                comment_lines(node.end_comments, indent + "\t")
                out.append(f"{indent}}}")
                if depth > 0 and idx < len(node_list) - 1:
                    out.append("")
            else:
                key = _quote(node.key)
                pad = " " * max(1, width - len(key) + 1)
                out.append(f"{indent}{key}{pad}{_quote(node.value)}{cond}{tail}")

    write(nodes, 0)
    if trailing_comments:
        comment_lines(trailing_comments, "")
    return "\n".join(out) + "\n"
