#!/usr/bin/env python3
"""Тесты извлечения текста из .docx. Запуск: python3 test_docx_text.py

Проверяем ровно то, ради чего экстрактор писался своими руками:
таблицы строками «ячейка | ячейка» и сохранённые адреса гиперссылок.
"""
import os
import shutil
import zipfile

import docx_text

TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp_docx")

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _docx(name, body_xml, rels_xml=""):
    """Собирает минимальный .docx из xml, без внешних библиотек."""
    os.makedirs(TMP, exist_ok=True)
    path = os.path.join(TMP, name)
    rels = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.'
            'openxmlformats.org/package/2006/relationships">%s</Relationships>' % rels_xml)
    doc = ('<?xml version="1.0"?><w:document xmlns:w="%s" xmlns:r="%s">'
           '<w:body>%s</w:body></w:document>' % (W, R, body_xml))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", doc)
        z.writestr("word/_rels/document.xml.rels", rels)
    return path


def _p(text):
    return "<w:p><w:r><w:t>%s</w:t></w:r></w:p>" % text


def test_paragraphs_become_lines():
    path = _docx("p.docx", _p("Общие сведения") + _p("Часовой пояс: UTC"))
    assert docx_text.extract(path).splitlines() == ["Общие сведения", "Часовой пояс: UTC"]


def test_table_rows_use_pipe_separator():
    """Детерминированные проверки разбирают таблицы по « | ». Плоский текст
    ломает разбор колонки сериализации и признака обязательности."""
    row = ("<w:tr>" + "".join("<w:tc>%s</w:tc>" % _p(c)
                              for c in ("Источник", "Kafka", "—")) + "</w:tr>")
    path = _docx("t.docx", "<w:tbl>%s</w:tbl>" % row)
    assert docx_text.extract(path).strip() == "Источник | Kafka | —"


def test_hyperlink_url_is_preserved():
    """Кейсодатель отбил два замечания словами «тут есть гиперссылка».
    В плоском тексте адреса нет — проверка ссылок ошибалась именно поэтому."""
    body = ('<w:p><w:r><w:t>Ссылка на Дата-каталог: </w:t></w:r>'
            '<w:hyperlink r:id="rId7"><w:r><w:t>карточка</w:t></w:r></w:hyperlink></w:p>')
    rels = ('<Relationship Id="rId7" Type="%s/hyperlink" '
            'Target="https://datacatalog.corp/x" TargetMode="External"/>' % R)
    text = docx_text.extract(_docx("h.docx", body, rels))
    assert "https://datacatalog.corp/x" in text, text
    assert "карточка" in text


def test_internal_anchor_is_not_rendered_as_address():
    """Якорь внутрь документа — не внешний адрес, подставлять его нельзя."""
    body = ('<w:p><w:hyperlink r:id="rId8"><w:r><w:t>см. выше</w:t></w:r>'
            '</w:hyperlink></w:p>')
    rels = ('<Relationship Id="rId8" Type="%s/hyperlink" Target="#anchor"/>' % R)
    text = docx_text.extract(_docx("a.docx", body, rels))
    assert text.strip() == "см. выше", text


def test_old_style_field_hyperlink():
    body = ('<w:p><w:fldSimple w:instr=\'HYPERLINK "https://gitlab.corp/p"\'>'
            '<w:r><w:t>исходники</w:t></w:r></w:fldSimple></w:p>')
    assert "https://gitlab.corp/p" in docx_text.extract(_docx("f.docx", body))


def test_blank_lines_are_collapsed():
    path = _docx("b.docx", _p("А") + _p("") + _p("") + _p("Б"))
    assert docx_text.extract(path).splitlines() == ["А", "", "Б"]


def test_zip_without_document_is_rejected():
    os.makedirs(TMP, exist_ok=True)
    path = os.path.join(TMP, "not.docx")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", "<x/>")       # это xlsx, а не docx
    try:
        docx_text.extract(path)
        raise AssertionError("ожидали NotADocx")
    except docx_text.NotADocx:
        pass


def test_count_links_counts_links_used_in_text():
    """Считаем ссылки, которые реально стоят в тексте, а не объявленные связи:
    связь без ссылки в теле документа читатель не увидит."""
    rels = ('<Relationship Id="r1" Type="%s/hyperlink" Target="https://a" TargetMode="External"/>'
            '<Relationship Id="r2" Type="%s/hyperlink" Target="#local"/>' % (R, R))
    body = ('<w:p><w:hyperlink r:id="r1"><w:r><w:t>внешняя</w:t></w:r></w:hyperlink>'
            '<w:hyperlink r:id="r2"><w:r><w:t>якорь</w:t></w:r></w:hyperlink></w:p>')
    assert docx_text.count_links(_docx("c.docx", body, rels)) == 1
    # объявленная, но неиспользованная связь ссылкой не считается
    assert docx_text.count_links(_docx("c2.docx", _p("текст"), rels)) == 0


def test_block_level_content_control_is_walked():
    """w:sdt оборачивает целые куски документа: плоский перебор детей тела
    пропустил бы их вместе с содержимым."""
    body = ('<w:sdt><w:sdtContent>'
            '<w:p><w:r><w:t>Общие сведения</w:t></w:r></w:p>'
            '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Поле</w:t></w:r></w:p></w:tc>'
            '<w:tc><w:p><w:r><w:t>string</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
            '</w:sdtContent></w:sdt>')
    lines = docx_text.extract(_docx("blocksdt.docx", body)).splitlines()
    assert lines == ["Общие сведения", "Поле | string"], lines


def test_split_instruction_of_composite_field_is_counted():
    """Word обычно режет инструкцию поля на несколько w:instrText —
    поиск регуляркой по сырому xml такую ссылку теряет."""
    body = ('<w:p>'
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText> HYPER</w:instrText></w:r>'
            '<w:r><w:instrText>LINK "https://sp</w:instrText></w:r>'
            '<w:r><w:instrText>lit.corp/x" </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            '<w:r><w:t>каталог</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
    path = _docx("split.docx", body)
    assert docx_text.count_links(path) == 1
    assert "https://split.corp/x" in docx_text.extract(path)


def test_text_inside_tracked_change_and_content_control():
    """В согласованном ТЗ полно правок в режиме рецензирования и контролов
    содержимого. Текст внутри них — обычный текст документа."""
    body = ('<w:p><w:ins><w:r><w:t>Часовой пояс: UTC</w:t></w:r></w:ins></w:p>'
            '<w:p><w:sdt><w:sdtContent><w:r><w:t>Раздел из контрола</w:t></w:r>'
            '</w:sdtContent></w:sdt></w:p>')
    lines = docx_text.extract(_docx("ins.docx", body)).splitlines()
    assert lines == ["Часовой пояс: UTC", "Раздел из контрола"], lines


def test_deleted_text_is_not_extracted():
    """Удалённое в режиме рецензирования из документа уже убрано."""
    body = ('<w:p><w:r><w:t>Осталось</w:t></w:r>'
            '<w:del><w:r><w:delText> и удалено</w:delText></w:r></w:del></w:p>')
    assert docx_text.extract(_docx("del.docx", body)).strip() == "Осталось"


def test_composite_hyperlink_field():
    """Классическое составное поле: begin → instrText → separate → текст → end."""
    body = ('<w:p>'
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText> HYPERLINK "https://confluence.corp/page" </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            '<w:r><w:t>Дата-каталог</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
    text = docx_text.extract(_docx("fld.docx", body))
    assert "https://confluence.corp/page" in text and "Дата-каталог" in text, text


def test_image_relationship_is_not_counted_as_link():
    """Во внешних связях лежат ещё изображения — ссылками они не являются."""
    rels = ('<Relationship Id="r1" Type="%s/image" Target="https://cdn/pic.png" '
            'TargetMode="External"/>' % R)
    path = _docx("img.docx", _p("текст"), rels)
    assert docx_text.count_links(path) == 0


def test_count_links_counts_field_hyperlinks():
    body = ('<w:p><w:fldSimple w:instr=\'HYPERLINK "https://a/b"\'>'
            '<w:r><w:t>ссылка</w:t></w:r></w:fldSimple></w:p>')
    assert docx_text.count_links(_docx("cf.docx", body)) == 1


def test_broken_rels_is_reported_as_not_docx():
    """Битый rels не должен ронять CLI трейсбеком без контрактного JSON."""
    path = _docx("badrels.docx", _p("текст"))
    import zipfile as _z
    data = {n: _z.ZipFile(path).read(n) for n in _z.ZipFile(path).namelist()}
    data["word/_rels/document.xml.rels"] = b"<Relationships><broken"
    with _z.ZipFile(path, "w") as z:
        for n, b in data.items():
            z.writestr(n, b)
    try:
        docx_text.extract(path)
        raise AssertionError("ожидали NotADocx")
    except docx_text.NotADocx as e:
        assert "rels" in str(e), e


if __name__ == "__main__":
    test_paragraphs_become_lines()
    test_table_rows_use_pipe_separator()
    test_hyperlink_url_is_preserved()
    test_internal_anchor_is_not_rendered_as_address()
    test_old_style_field_hyperlink()
    test_blank_lines_are_collapsed()
    test_zip_without_document_is_rejected()
    test_count_links_counts_links_used_in_text()
    test_block_level_content_control_is_walked()
    test_split_instruction_of_composite_field_is_counted()
    test_text_inside_tracked_change_and_content_control()
    test_deleted_text_is_not_extracted()
    test_composite_hyperlink_field()
    test_image_relationship_is_not_counted_as_link()
    test_count_links_counts_field_hyperlinks()
    test_broken_rels_is_reported_as_not_docx()
    shutil.rmtree(TMP, ignore_errors=True)
    print("все тесты пройдены")
