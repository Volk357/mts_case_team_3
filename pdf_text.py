#!/usr/bin/env python3
"""
Извлечение текста из .pdf.

Почему здесь, в отличие от .docx, взята библиотека, а не свой разбор.
В .docx текст лежит открытым XML, и свой экстрактор дал нам то, чего готовые
библиотеки не дают: таблицы строками «ячейка | ячейка» и адреса гиперссылок.
В .pdf текст лежит в сжатых потоках, а расположение символов задаётся
координатами и кодировками шрифтов, вплоть до CID. Свой разбор пришлось бы
доводить под каждый генератор PDF, и на документе заказчика он выдал бы
правдоподобный мусор — худший из возможных исходов для инструмента, который
цитирует документ дословно. Поэтому pypdf: чистый Python, без бинарных
зависимостей, ставится в тот же venv.

Чего PDF не даёт по своей природе, и об этом честно предупреждаем:

  1. ТАБЛИЦЫ. В PDF таблицы — это линии и текст с координатами, разметки
     ячеек в файле нет вовсе. Строки «ячейка | ячейка» восстановить нельзя,
     а половина детерминированных проверок разбирает документ именно так.
     Полнота на PDF будет ниже, чем на том же документе в .docx.

  2. ГИПЕРССЫЛКИ. Адреса лежат в аннотациях страницы, а не в тексте. Мы их
     собираем и дописываем в конец, чтобы проверка «есть ли ссылка на
     Дата-каталог» видела то же, что видит человек.

Скан без текстового слоя отдаёт пустоту. Это отдельная ошибка, а не пустой
анализ: молчаливое «замечаний нет» на сканированном документе обманывает
сильнее, чем отказ. По той же причине `extract` возвращает не только текст,
но и число страниц, которые не удалось прочитать: анализ неполного документа,
выданный как полный, — та же ложь, только тише.
"""


class PdfSupportMissing(Exception):
    """В окружении нет pypdf — извлечь текст нечем."""


class NotAPdf(Exception):
    """Файл не открывается как PDF (повреждён или это не PDF)."""


class NoTextLayer(Exception):
    """PDF без текстового слоя: скан или картинки без распознавания."""


def _reader(path):
    try:
        from pypdf import PdfReader
    except ImportError as error:  # pragma: no cover - зависит от окружения
        raise PdfSupportMissing(
            "Для чтения PDF нужен пакет pypdf: pip install pypdf"
        ) from error
    try:
        return PdfReader(path)
    except Exception as error:
        raise NotAPdf(str(error)) from error


def _page_links(page):
    """Адреса ссылок со страницы: в PDF они лежат в аннотациях, не в тексте."""
    urls = []
    try:
        annotations = page.get("/Annots") or []
    except Exception:
        return urls
    for annotation in annotations:
        try:
            obj = annotation.get_object()
            action = obj.get("/A")
            if not action:
                continue
            uri = action.get_object().get("/URI")
            if uri:
                urls.append(str(uri))
        except Exception:
            # Битую аннотацию пропускаем: из-за неё нельзя терять весь документ.
            continue
    return urls


def extract(path):
    """Возвращает (текст, отчёт о разборе).

    Отчёт содержит `pages` и `unreadable_pages`. Вызывающая сторона обязана
    показать наружу предупреждение, если страницы потерялись: анализ по части
    документа, выданный как анализ документа, вводит в заблуждение ровно так
    же, как пустой результат на скане.
    """
    reader = _reader(path)

    try:
        pages = list(reader.pages)
    except Exception as error:
        raise NotAPdf(str(error)) from error

    chunks = []
    links = []
    unreadable = 0
    for page in pages:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:
            # Страница повреждена. Остальные всё равно полезны, но потерю
            # нельзя проглатывать — считаем и сообщаем.
            chunks.append("")
            unreadable += 1
        links.extend(_page_links(page))

    text = "\n\n".join(chunk.strip() for chunk in chunks if chunk.strip())
    if not text.strip():
        raise NoTextLayer(
            "В PDF нет текстового слоя (%d страниц). Похоже на скан: "
            "распознайте документ или пришлите .docx." % len(pages)
        )

    if links:
        seen = []
        for url in links:
            if url not in seen:
                seen.append(url)
        text += "\n\nСсылки в документе:\n" + "\n".join(seen)
    return text, {"pages": len(pages), "unreadable_pages": unreadable}


def count_pages(path):
    """Сколько страниц. Нужно для предупреждений и диагностики."""
    return len(_reader(path).pages)


def count_links(path):
    """Сколько внешних ссылок нашлось в аннотациях."""
    total = 0
    for page in _reader(path).pages:
        total += len(_page_links(page))
    return total


if __name__ == "__main__":  # pragma: no cover
    import sys

    body, report = extract(sys.argv[1])
    print(body)
    print("\n--- страниц: %(pages)d, нечитаемых: %(unreadable_pages)d" % report)
