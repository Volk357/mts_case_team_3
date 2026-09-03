"""
Модель документа и рендерер.

Документ — дерево узлов с устойчивыми id. Мутаторы правят дерево,
рендер выполняется ОДИН раз после всех мутаций. Цитата эталона берётся
из отрендеренного текста по id узла-якоря, поэтому дословность цитаты
обеспечена по построению, а не проверкой постфактум.
"""

from __future__ import annotations


class Node:
    """Узел документа. kind определяет способ рендера."""

    def __init__(self, nid, kind, text="", title="", headers=None, na=False):
        self.id = nid
        self.kind = kind          # section | para | kv | kvrow | table | row | steps | step | line
        self.text = text
        self.title = title
        self.headers = headers or []
        self.na = na
        self.children: list[Node] = []
        self.parent: Node | None = None

    def add(self, node: Node) -> Node:
        node.parent = self
        self.children.append(node)
        return node

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


class Doc:
    """Документ целиком. Хранит секции и индекс узлов по id."""

    def __init__(self, doc_id: str, title: str):
        self.id = doc_id
        self.title = title
        self.root = Node(doc_id, "root")
        self._rendered: dict[str, str] = {}

    # --- построение -------------------------------------------------

    def section(self, sid, title, na=False) -> Node:
        return self.root.add(Node(sid, "section", title=title, na=na))

    # --- поиск ------------------------------------------------------

    def find(self, nid: str) -> Node:
        for n in self.root.walk():
            if n.id == nid:
                return n
        raise KeyError(f"узел не найден: {nid}")

    def has(self, nid: str) -> bool:
        return any(n.id == nid for n in self.root.walk())

    def order(self) -> list[Node]:
        """Все узлы в порядке следования в документе."""
        return list(self.root.walk())

    def prev_leaf(self, nid: str) -> str:
        """
        id предыдущего листового узла — кандидат в якорь для дефектов
        удаления. Если предыдущего нет, возвращает заголовок секции.
        """
        target = self.find(nid)
        subtree = {n.id for n in target.walk()}
        prev = None
        for n in self.order():
            if n.id in subtree:
                break
            if n.kind in ("line", "para", "kvrow", "row"):
                prev = n.id
        if prev:
            return prev
        sec = target
        while sec is not None and sec.kind != "section":
            sec = sec.parent
        if sec is None:
            raise ValueError(f"нет якоря для {nid}")
        return sec.id

    # --- изменение --------------------------------------------------

    def remove(self, nid: str):
        node = self.find(nid)
        node.parent.children.remove(node)

    def set_text(self, nid: str, text: str):
        self.find(nid).text = text

    def set_cell(self, nid: str, col: int, value: str):
        self.find(nid).cells[col] = value

    def insert_after(self, nid: str, node: Node):
        ref = self.find(nid)
        idx = ref.parent.children.index(ref)
        node.parent = ref.parent
        ref.parent.children.insert(idx + 1, node)

    def append_to(self, nid: str, node: Node):
        self.find(nid).add(node)

    # --- рендер -----------------------------------------------------

    def render(self) -> str:
        self._rendered = {}
        lines: list[str] = []
        for sec in self.root.children:
            self._render_node(sec, lines)
        text = "\n".join(lines).rstrip() + "\n"
        return text

    def _render_node(self, node: Node, lines: list[str]):
        start = len(lines)

        if node.kind == "section":
            lines.append(node.title)
            if node.na:
                lines.append("не применимо")
            else:
                for c in node.children:
                    self._render_node(c, lines)
            lines.append("")

        elif node.kind in ("para", "line"):
            lines.append(node.text)

        elif node.kind == "kv":
            for c in node.children:
                self._render_node(c, lines)

        elif node.kind == "kvrow":
            lines.append(f"{node.title}: {node.text}" if node.title else node.text)

        elif node.kind == "table":
            if node.title:
                lines.append(node.title)
            lines.append(" | ".join(node.headers))
            for c in node.children:
                self._render_node(c, lines)

        elif node.kind == "row":
            lines.append(" | ".join(node.cells).rstrip())

        elif node.kind == "steps":
            for c in node.children:
                self._render_node(c, lines)

        elif node.kind == "step":
            lines.append(node.title)
            for c in node.children:
                self._render_node(c, lines)

        else:
            raise ValueError(f"неизвестный kind: {node.kind}")

        end = len(lines)
        block = "\n".join(x for x in lines[start:end] if x != "").strip()
        self._rendered[node.id] = block

    def text_of(self, nid: str) -> str:
        """Отрендеренный текст узла. Вызывать только после render()."""
        if nid not in self._rendered:
            raise KeyError(f"узел {nid} отсутствует в отрендеренном документе")
        return self._rendered[nid]


class RowNode(Node):
    """Строка таблицы. Ячейки редактируются мутаторами по индексу."""

    def __init__(self, nid, cells):
        super().__init__(nid, "row")
        self.cells = list(cells)


def row(nid, cells) -> RowNode:
    return RowNode(nid, cells)


def para(nid, text) -> Node:
    return Node(nid, "para", text=text)


def line(nid, text) -> Node:
    return Node(nid, "line", text=text)


def kv(nid) -> Node:
    return Node(nid, "kv")


def kvrow(nid, key, value) -> Node:
    return Node(nid, "kvrow", title=key, text=value)


def table(nid, headers, caption="") -> Node:
    return Node(nid, "table", headers=headers, title=caption)


def steps(nid) -> Node:
    return Node(nid, "steps")


def step(nid, title) -> Node:
    return Node(nid, "step", title=title)
