#!/usr/bin/env python3
"""
Извлечение текста из .docx — только стандартная библиотека.

Зачем свой экстрактор, а не python-docx. Во-первых, ядро работает в закрытом
контуре, и лишняя зависимость — лишний разговор с безопасностью. Во-вторых,
готовые библиотеки отдают «плоский» текст, а нам нужны две вещи, которых там
нет по умолчанию:

  1. ТАБЛИЦЫ строками вида «ячейка | ячейка | ячейка». Половина
     детерминированных проверок разбирает документ именно так: колонка
     сериализации, признак обязательности, типы полей в структуре данных.
     Плоский текст ломает их все.

  2. ГИПЕРССЫЛКИ. Это не косметика: кейсодатель отбил два наших замечания
     словами «тут есть гиперссылка, не ошибка», а при конвертации в плоский
     текст адрес пропадал — и инструмент снова считал ссылку отсутствующей.
     В .docx адрес лежит не в тексте абзаца, а в word/_rels/document.xml.rels,
     и вытащить его можно только разобрав связи. Мы дописываем адрес рядом
     с текстом ссылки, поэтому проверка «есть ли ссылка на Дата-каталог»
     видит то же, что видит человек, открывший документ.

Формат .docx — zip с xml. Разбираем word/document.xml потоково по элементам
тела: абзацы дают строки, таблицы — строки с разделителем.
"""

import re
import zipfile
from xml.etree import ElementTree

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

DOCUMENT = "word/document.xml"
DOCUMENT_RELS = "word/_rels/document.xml.rels"


class NotADocx(Exception):
    """Файл не является .docx (нет обязательных частей пакета)."""


HYPERLINK_REL = "/hyperlink"
# Элементы без видимого текста и удалённый текст правок: в извлечение не идут.
# w:del — это удалённое в режиме рецензирования, его в документе уже нет.
SKIP_TAGS = {W + "proofErr", W + "bookmarkStart", W + "bookmarkEnd",
             W + "del", W + "commentRangeStart", W + "commentRangeEnd",
             W + "lastRenderedPageBreak", W + "sectPr", W + "pPr", W + "rPr"}

_HYPERLINK_FIELD = re.compile(r'HYPERLINK\s+"([^"]+)"')


def _load_links(archive):
    """id связи → внешний адрес.

    Берём только связи типа hyperlink: во внешних связях лежат ещё изображения
    и вложения, и считать их ссылками нельзя — иначе документ без единой ссылки
    выглядел бы как документ со ссылками. Якоря внутрь документа (#anchor)
    адресом не являются.
    """
    try:
        raw = archive.read(DOCUMENT_RELS)
    except KeyError:
        return {}
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as e:
        raise NotADocx("повреждён %s: %s" % (DOCUMENT_RELS, e))
    links = {}
    for rel in root:
        target = rel.get("Target", "")
        if (rel.get("TargetMode") == "External" and target
                and rel.get("Type", "").endswith(HYPERLINK_REL)):
            links[rel.get("Id")] = target
    return links


def _render_link(text, url):
    """Текст ссылки вместе с адресом: адрес и есть то, что теряется
    при плоской конвертации."""
    text = text.strip()
    if not url:
        return text
    if url in text:
        return text
    return "%s (%s)" % (text, url) if text else url


def _runs_text(node):
    """Весь видимый текст внутри узла, включая обёртки правок и контролов."""
    out = []
    for child in node:
        if child.tag in SKIP_TAGS:
            continue
        if child.tag == W + "t":
            out.append(child.text or "")
        elif child.tag in (W + "tab", W + "br", W + "cr"):
            out.append(" ")
        else:
            out.append(_runs_text(child))
    return "".join(out)


def _paragraph_text(node, links, counter=None):
    """Текст абзаца с сохранёнными адресами ссылок.

    Обходим дерево рекурсивно: видимый текст лежит не только в прямых w:r,
    но и внутри w:ins (правка в режиме рецензирования), w:sdt (контрол
    содержимого) и подобных обёрток — в согласованном ТЗ этого много.

    Ссылки в docx бывают трёх видов, и все три встречаются в живых файлах:
      1. w:hyperlink с r:id — адрес в связях;
      2. w:fldSimple с инструкцией HYPERLINK "…";
      3. составное поле: fldChar begin → instrText HYPERLINK "…" →
         fldChar separate → текст → fldChar end.
    Третий вид разбирается автоматом состояний ниже.
    """
    parts = []
    field = {"stage": None, "instr": [], "text": []}

    def note_link(url):
        # Считаем ссылки здесь же: инструкция составного поля в Word обычно
        # разбита на несколько w:instrText, и поиск регуляркой по сырому xml
        # такую ссылку не находит. Один проход по дереву — один источник правды.
        if url and counter is not None:
            counter.append(url)

    def close_field():
        if field["stage"]:
            url = _HYPERLINK_FIELD.search("".join(field["instr"]))
            url = url.group(1) if url else None
            note_link(url)
            parts.append(_render_link("".join(field["text"]), url))
        field.update(stage=None, instr=[], text=[])

    def emit(text):
        if field["stage"] == "result":
            field["text"].append(text)
        else:
            parts.append(text)

    def walk(element):
        for child in element:
            tag = child.tag
            if tag in SKIP_TAGS:
                continue
            if tag == W + "hyperlink":
                url = links.get(child.get(R + "id"))
                note_link(url)
                emit(_render_link(_runs_text(child), url))
            elif tag == W + "fldSimple":
                url = _HYPERLINK_FIELD.search(child.get(W + "instr", "") or "")
                url = url.group(1) if url else None
                note_link(url)
                emit(_render_link(_runs_text(child), url))
            elif tag == W + "fldChar":
                kind = child.get(W + "fldCharType")
                if kind == "begin":
                    close_field()
                    field["stage"] = "instr"
                elif kind == "separate":
                    field["stage"] = "result"
                elif kind == "end":
                    close_field()
            elif tag == W + "instrText":
                field["instr"].append(child.text or "")
            elif tag == W + "t":
                emit(child.text or "")
            elif tag in (W + "tab", W + "br", W + "cr"):
                emit(" ")
            else:
                walk(child)

    walk(node)
    close_field()
    return re.sub(r"[ \t]+", " ", "".join(parts)).strip()


def _table_lines(node, links, counter=None):
    """Строки таблицы в том же виде, в каком их ждут детерминированные
    проверки: ячейки через « | ». Вложенные таблицы разворачиваются в текст
    ячейки, а не в отдельные строки — иначе поедет разбор колонок."""
    lines = []
    for row in node.findall(W + "tr"):
        cells = []
        for cell in row.findall(W + "tc"):
            chunks = [_paragraph_text(p, links, counter) for p in cell.findall(W + "p")]
            chunks += [" ".join(_paragraph_text(p, links, counter)
                                for p in inner.iter(W + "p"))
                       for inner in cell.findall(W + "tbl")]
            cells.append(" ".join(c for c in chunks if c).strip())
        if any(cells):
            lines.append(" | ".join(cells))
    return lines


def _blocks(node):
    """Абзацы и таблицы в порядке документа, включая вложенные в контейнеры.

    Тело документа содержит не только w:p и w:tbl напрямую: блочный w:sdt
    (контрол содержимого) оборачивает целые куски документа, и его дети —
    такие же абзацы и таблицы. Плоский перебор детей тела пропустил бы их
    целиком вместе с содержимым.
    """
    for child in node:
        tag = child.tag
        if tag in SKIP_TAGS:
            continue
        if tag in (W + "p", W + "tbl"):
            yield child
        else:
            yield from _blocks(child)


def _read_document_parts(path):
    """Один проход по документу: (строки, найденные адреса ссылок)."""
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as e:
        raise NotADocx("не zip-контейнер: %s" % e)
    with archive:
        if DOCUMENT not in archive.namelist():
            raise NotADocx("в пакете нет %s" % DOCUMENT)
        links = _load_links(archive)
        try:
            body = ElementTree.fromstring(archive.read(DOCUMENT)).find(W + "body")
        except ElementTree.ParseError as e:
            raise NotADocx("повреждён %s: %s" % (DOCUMENT, e))
        if body is None:
            raise NotADocx("в %s нет тела документа" % DOCUMENT)

        found, lines = [], []
        for node in _blocks(body):
            if node.tag == W + "p":
                lines.append(_paragraph_text(node, links, found))
            else:
                lines.extend(_table_lines(node, links, found))
        return lines, found


def extract(path):
    """Текст документа: абзацы построчно, таблицы строками с « | »."""
    lines, _ = _read_document_parts(path)
    # Схлопываем подряд идущие пустые строки: в docx их обычно много,
    # а разбор разделов ориентируется на соседство строк.
    out, blank = [], False
    for line in lines:
        if line:
            out.append(line)
            blank = False
        elif not blank:
            out.append("")
            blank = True
    return "\n".join(out).strip() + "\n"


def count_links(path):
    """Сколько ссылок в документе — по всем трём способам их записи.

    Считаем тем же проходом, что и извлекает текст: инструкция составного поля
    бывает разбита на несколько w:instrText, и поиск по сырому xml её теряет.
    Нужно для отчёта: если ссылок нет вовсе, замечания об отсутствующих
    ссылках надо читать с поправкой.
    """
    _, found = _read_document_parts(path)
    return len(found)


if __name__ == "__main__":
    import sys
    print(extract(sys.argv[1]))
