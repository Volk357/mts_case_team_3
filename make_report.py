#!/usr/bin/env python3
"""
Собирает markdown-отчёт для кейсодателя из результатов прогона.

Отчёт короткий и без внутренней кухни: только замечания и пометки
кейсодателя. Никаких процентов, гипотез и разбора ошибок модели —
это для артефактов хакатона, не для заказчика.

Отличия от первой версии и причины:

1. explanation печатается целиком, в теле замечания. Раньше он
   уходил в заголовок с обрезкой до 90 символов, то есть терялся.
   Объяснение — главное содержание замечания: цитата показывает
   место, рекомендация — что дописать, а почему это проблема,
   говорит только оно.

2. Цитата не чистится и не обрезается, печатается блоком as is.
   Раньше clean() менял "|" на "/" — а половина цитат это строки
   таблиц вида "FIELD_BIZ_DATE | date | Бизнес-дата". С подменённым
   разделителем кейсодатель не найдёт цитату у себя в документе,
   а дословность цитаты — центральная гарантия инструмента.

3. У каждого замечания печатается id: тип дефекта и короткий хэш,
   тот же, что использует mark_findings.py (md5 от quote+explanation).
   Это позволяет свести ответы кейсодателя с нашей разметкой
   автоматически, а не глазами.

4. Пометка — пять фиксированных категорий контура обратной связи
   вместо свободного текста. Ответ сразу становится данными.

5. Порядок замечаний перемешивает типы. Сортировка только по
   важности выносит наверх подряд несколько замечаний одного типа,
   и первый экран выглядит однообразным.

Использование:
    python3 make_report.py --doc vitrina --mode full
    python3 make_report.py --doc vitrina --mode full --title "Описание витрины-агрегата"
"""

import argparse
import hashlib
import json
from pathlib import Path

import yaml

SEVERITY_RU = {"high": "высокая", "medium": "средняя", "low": "низкая"}
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

# Категории контура обратной связи. Порядок важен: первым идёт
# подтверждение, чтобы отметка по умолчанию не была отрицательной.
MARKS = [
    ("accepted", "по делу, поправлю документ"),
    ("false_positive", "ложное срабатывание, в документе этого нет"),
    ("allowed_exception", "так задумано, опущено сознательно"),
    ("already_described", "это уже описано в другом месте документа"),
    ("not_relevant", "не относится к этому документу"),
]


def finding_id(f):
    """Тот же ключ, что в mark_findings.py: md5 от quote + explanation."""
    raw = f.get("quote", "") + f.get("explanation", "")
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def load_defect_names(path):
    """id -> человекочитаемое название типа. Нужно для заголовков."""
    p = Path(path)
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    return {d["id"]: d.get("name", d["id"]) for d in data.get("defects", [])}


def flow(text):
    """Схлопывает переносы в абзаце. Применяется к объяснению и
    рекомендации, но НИКОГДА к цитате."""
    return " ".join(str(text or "").split())


def order(findings):
    """
    Важность сохраняем как основной приоритет, но не даём двум
    замечаниям одного типа встать рядом: жадно берём самое важное
    из доступных, у которого тип отличается от предыдущего.
    """
    rest = sorted(findings,
                  key=lambda f: SEVERITY_ORDER.get(f.get("severity"), 1))
    result, last_type = [], None

    while rest:
        pick = next((f for f in rest if f.get("defect_id") != last_type), rest[0])
        rest.remove(pick)
        result.append(pick)
        last_type = pick.get("defect_id")

    return result


SUMMARY_HINT = ("Отметьте по каждому одну категорию. Если замечание по делу, "
                "достаточно первой. Комментарий по желанию — особенно там, где "
                "инструмент ошибся: этим он настраивается под ваши соглашения.")


def block_quote(q):
    """Многострочные цитаты и строки таблиц — блоком, короткие — строкой."""
    return "\n" in q or "|" in q


def render_md(findings, title, names):
    out = [f"# Предварительное ревью: {title}", "",
           f"Замечаний: {len(findings)}. {SUMMARY_HINT}", "",
           "| № | Что не так | Важность |", "|---|---|---|"]

    for i, f in enumerate(findings, 1):
        did = f.get("defect_id", "")
        out.append(f"| {i} | {names.get(did, did)} | "
                   f"{SEVERITY_RU.get(f.get('severity','medium'),'средняя')} |")
    out.append("")

    for i, f in enumerate(findings, 1):
        did = f.get("defect_id", "")
        q = f.get("quote", "")
        out += [f"## {i}. {names.get(did, did)}", ""]
        out += ["```", q, "```", ""] if block_quote(q) else [f"> {q}", ""]
        out += [flow(f.get("explanation")), "",
                f"*Уточнить:* {flow(f.get('suggestion'))}", "",
                "Оценка: " + "  ".join(f"☐ {lbl}" for _, lbl in MARKS),
                "", f"<sub>{did} · {finding_id(f)}</sub>", ""]

    return "\n".join(out)


HTML_HEAD = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
@page { size: A4; margin: 14mm 14mm 12mm; }
body { font: 10pt/1.45 "DejaVu Sans", sans-serif; color: #111; }
h1 { font-size: 15pt; margin: 0 0 2mm; }
p.lead { font-size: 9pt; color: #444; margin: 0 0 4mm; }
table.toc { border-collapse: collapse; width: 100%; font-size: 9pt;
            margin-bottom: 6mm; }
table.toc td, table.toc th { border-bottom: 1px solid #ddd;
            padding: 1.5mm 2mm; text-align: left; }
table.toc th { background: #f4f4f4; }
td.n { width: 8mm; color: #777; }
td.sev { width: 22mm; color: #555; }
div.f { page-break-inside: avoid; margin-bottom: 5mm;
        border-top: 1px solid #ddd; padding-top: 3mm; }
h2 { font-size: 10.5pt; margin: 0 0 2mm; }
h2 span.num { color: #999; }
pre, blockquote { background: #f6f6f6; border-left: 2px solid #bbb;
        margin: 0 0 2mm; padding: 2mm 3mm; font-size: 8.5pt;
        font-family: "DejaVu Sans Mono", monospace; white-space: pre-wrap;
        word-wrap: break-word; }
p { margin: 0 0 2mm; }
p.sg { color: #333; }
p.mark { font-size: 9pt; margin-top: 2.5mm; }
p.id { font-size: 7.5pt; color: #aaa; margin: 0; }
</style></head><body>"""


def esc(t):
    return (str(t or "").replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;"))


def render_html(findings, title, names):
    out = [HTML_HEAD, f"<h1>Предварительное ревью: {esc(title)}</h1>",
           f'<p class="lead">Замечаний: {len(findings)}. {esc(SUMMARY_HINT)}</p>',
           '<table class="toc"><tr><th>№</th><th>Что не так</th>'
           '<th>Важность</th></tr>']

    for i, f in enumerate(findings, 1):
        did = f.get("defect_id", "")
        out.append(f'<tr><td class="n">{i}</td><td>{esc(names.get(did, did))}'
                   f'</td><td class="sev">'
                   f'{SEVERITY_RU.get(f.get("severity","medium"),"средняя")}'
                   "</td></tr>")
    out.append("</table>")

    for i, f in enumerate(findings, 1):
        did = f.get("defect_id", "")
        q = esc(f.get("quote", ""))
        body = f"<pre>{q}</pre>" if block_quote(f.get("quote", "")) \
            else f"<blockquote>{q}</blockquote>"
        marks = "&nbsp; ".join(f"&#9744; {esc(l)}" for _, l in MARKS)
        out.append(
            f'<div class="f"><h2><span class="num">{i}.</span> '
            f'{esc(names.get(did, did))}</h2>{body}'
            f"<p>{esc(flow(f.get('explanation')))}</p>"
            f'<p class="sg"><i>Уточнить:</i> {esc(flow(f.get("suggestion")))}</p>'
            f'<p class="mark">Оценка: {marks}</p>'
            f'<p class="id">{esc(did)} · {finding_id(f)}</p></div>')

    out.append("</body></html>")
    return "\n".join(out)


def to_pdf(html_text, out_pdf):
    """wkhtmltopdf: единственный путь с нормальной кириллицей из коробки."""
    import subprocess, tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(html_text)
        src = fh.name
    subprocess.run(["wkhtmltopdf", "--quiet", "--encoding", "utf-8",
                    "--enable-local-file-access", src, str(out_pdf)],
                   check=True)
    return out_pdf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", required=True, help="например vitrina")
    ap.add_argument("--mode", default="full")
    ap.add_argument("--results", default="results")
    ap.add_argument("--defects", default="defects.yaml")
    ap.add_argument("--out", default=None)
    ap.add_argument("--format", default="both", choices=["md", "pdf", "both"])
    ap.add_argument("--title", default=None,
                    help="как назвать документ в шапке отчёта")
    args = ap.parse_args()

    path = Path(args.results) / f"{args.doc}_{args.mode}.json"
    data = json.loads(path.read_text(encoding="utf-8"))

    findings = order(data["findings"])
    names = load_defect_names(args.defects)

    stem = Path(args.out).with_suffix("") if args.out else Path(f"review_{args.doc}")
    made = []

    if args.format in ("md", "both"):
        p = stem.with_suffix(".md")
        p.write_text(render_md(findings, args.title or args.doc, names),
                     encoding="utf-8")
        made.append(p)

    if args.format in ("pdf", "both"):
        p = stem.with_suffix(".pdf")
        to_pdf(render_html(findings, args.title or args.doc, names), p)
        made.append(p)

    types = len({f.get("defect_id") for f in findings})
    adjacent = sum(1 for a, b in zip(findings, findings[1:])
                   if a.get("defect_id") == b.get("defect_id"))
    print("Готово: " + ", ".join(str(p) for p in made))
    print(f"  замечаний: {len(findings)}, типов: {types}, "
          f"подряд одного типа: {adjacent}")


if __name__ == "__main__":
    main()
