#!/usr/bin/env python3
"""CLI `docreview` — мост Analysis Core → Product Application по контракту v1.0.

Команда:
    docreview analyze --file <doc> --pack <review_pack> --run-id <id> --output <out.json>

Гоняет наш пайплайн (детерминированный слой + модель) и пишет ReviewResult JSON
по схеме contracts/review-result.schema.json. location.section_path берётся из
нашего детектора разделов; page/таблицы — POST-submission (page=null).

Ядро не знает про UI/HTTP/БД приложения — только файл на входе, JSON на выходе.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time

ENGINE_VERSION = "0.2.0"
SCHEMA_VERSION = "1.0"

# Наш severity → enum контракта (critical/high/medium/low). clarification → low.
_SEV_MAP = {"high": "high", "medium": "medium", "low": "low",
            "clarification": "low", "critical": "critical"}
_SEV_BASE = {"high": 0.85, "medium": 0.7, "low": 0.55, "clarification": 0.5,
             "critical": 0.9}


def _block_id(quote):
    return "q-" + hashlib.sha1((quote or "").encode("utf-8")).hexdigest()[:12]


def _confidence(finding, deterministic):
    if deterministic:
        return 0.95
    base = _SEV_BASE.get(finding.get("severity", "medium"), 0.6)
    base += 0.05 * (int(finding.get("merged_count", 1)) - 1)
    return round(max(0.05, min(0.99, base)), 2)


def _section_path(quote, lines, cfg, is_section_header):
    """Ближайший заголовок раздела шаблона выше цитаты. Настоящий section_path."""
    if not quote:
        return []
    head = quote.split("\n", 1)[0].strip()
    idx = next((i for i, ln in enumerate(lines) if head and head in ln), None)
    if idx is None:
        return []
    for j in range(idx, -1, -1):
        if is_section_header(lines[j], cfg):
            name = re.sub(r"\s+", " ", lines[j].strip())
            return [name]
    return []


def _map_finding(f, i, deterministic, lines, cfg, is_section_header):
    quote = f.get("quote", "") or ""
    did = f.get("defect_id", "UNKNOWN")
    if not re.match(r"^[A-Z][A-Z0-9_]*$", did):
        did = "UNKNOWN"
    return {
        "id": "f-%03d" % i,
        "defect_id": did,
        "severity": _SEV_MAP.get(f.get("severity", "medium"), "medium"),
        "confidence": _confidence(f, deterministic),
        "location": {
            "page": None,
            "section_path": _section_path(quote, lines, cfg, is_section_header),
            "block_id": _block_id(quote),
        },
        "quote": quote or "—",
        "problem": (f.get("explanation") or "Место требует уточнения.").strip() or "—",
        "clarification": (f.get("suggestion") or "Уточнить у аналитика.").strip() or "—",
        "detected_by": ["deterministic"] if deterministic else ["model"],
    }


def build_review_result(text, filename, document_type, formal_findings,
                        llm_findings, run_id, pack_id, model_name,
                        prompt_versions, total_ms, warnings=None,
                        total_candidates=None, verified_candidates=None):
    """Чистая сборка ReviewResult (completed). Тестируется без модели."""
    import check_formal
    cfg = check_formal.load_config("template.yaml")
    is_sh = check_formal.is_section_header
    lines = text.splitlines()

    findings, i = [], 0
    for f in formal_findings:
        findings.append(_map_finding(f, i, True, lines, cfg, is_sh)); i += 1
    for f in llm_findings:
        findings.append(_map_finding(f, i, False, lines, cfg, is_sh)); i += 1
    findings = findings[:20]                       # контракт: maxItems 20

    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in findings:
        counts[f["severity"]] += 1

    n = len(formal_findings) + len(llm_findings)
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "status": "completed",
        "document": {
            "filename": filename,
            "document_type": document_type,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        },
        "engine": {"version": ENGINE_VERSION},
        "review_pack": {"id": pack_id, "version": "0.2"},
        "model": {"name": model_name, "prompt_versions": prompt_versions},
        "findings": findings,
        "summary": {
            "total_candidates": int(total_candidates if total_candidates is not None else n),
            "verified_candidates": int(verified_candidates if verified_candidates is not None else n),
            "returned_findings": len(findings),
            **counts,
        },
        "warnings": warnings or [],
        "timings": {"total_ms": int(total_ms)},
    }


def failed_result(run_id, code, stage, message, retriable):
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "status": "failed",
        "error": {"code": code, "stage": stage, "message": message,
                  "retriable": bool(retriable)},
    }


def _read_document(path):
    """Читает документ в текст. txt/md — напрямую; pdf/docx — POST-submission."""
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    if ext in ("txt", "md", "markdown", ""):
        return open(path, encoding="utf-8", errors="replace").read(), ext or "txt", []
    # pdf/docx: полноценный парсер — POST-submission. Пробуем прочитать как текст.
    warn = [{"code": "PARSER_FALLBACK",
             "message": "Формат %s без структурного парсера; прочитан как текст, "
                        "привязка к странице/таблице недоступна." % ext}]
    return open(path, encoding="utf-8", errors="replace").read(), ext, warn


def cmd_analyze(args):
    t0 = time.time()
    run_id = args.run_id
    try:
        text, doc_type, warnings = _read_document(args.file)
    except OSError as e:
        _write(args.output, failed_result(run_id, "CORE_INPUT_UNREADABLE",
                                          "read", str(e), False))
        return 3

    try:
        import run_review
        import check_formal
        taxonomy_text, valid_ids, defects = run_review.load_taxonomy(args.defects)
        glossary_text = run_review.load_glossary(args.glossary)
        known = run_review.extract_known_objects(text)
        cfg = check_formal.load_config("template.yaml")
        formal = check_formal.run(text, cfg)["findings"]
        llm = run_review.run_full(text, defects, taxonomy_text, valid_ids, known,
                                  frag_mode="dict2", glossary_text=glossary_text,
                                  label="full2")
        result = build_review_result(
            text, os.path.basename(args.file), doc_type, formal, llm["findings"],
            run_id, args.pack, os.environ.get("OLLAMA_MODEL", "qwen3:30b-a3b"),
            {"fragment": "dict2", "global": "global"},
            (time.time() - t0) * 1000, warnings,
            total_candidates=llm["found_raw"] + len(formal),
            verified_candidates=llm["verified"] + len(formal))
    except Exception as e:                          # noqa: BLE001 — любой сбой → failed
        _write(args.output, failed_result(run_id, "CORE_PROCESS_FAILED",
                                          "analyze", str(e), True))
        return 1

    _write(args.output, result)
    return 0


def _write(path, obj):
    if path:
        json.dump(obj, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    else:
        json.dump(obj, sys.stdout, ensure_ascii=False, indent=2)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="docreview")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyze", help="проверить документ, выдать ReviewResult JSON")
    a.add_argument("--file", required=True)
    a.add_argument("--pack", default="mts-net-v0.2")
    a.add_argument("--run-id", required=True)
    a.add_argument("--output", default=None)
    a.add_argument("--defects", default="defects.yaml")
    a.add_argument("--glossary", default="glossary.yaml")
    args = ap.parse_args(argv)
    if args.cmd == "analyze":
        return cmd_analyze(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
