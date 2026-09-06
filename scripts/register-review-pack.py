#!/usr/bin/env python3
"""
Регистрация Review Pack в базе приложения.

Зачем скрипт, а не строка SQL в DEPLOY.md. Приложение показывает только те
пакеты, которые записаны в `review_pack_references`: файлы на диске сами по
себе каталог не наполняют. Пакет, выложенный без регистрации, невидим —
и это уже случилось с профилем `generic`, который лежал в каталоге, но
не появлялся в интерфейсе.

Скрипт читает идентичность из МАНИФЕСТА пакета, а не принимает её
аргументами: `pack_key` и `version` обязаны совпадать с тем, что вернёт
ядро в результате, иначе приложение забракует результат целиком.

Запуск на сервере:

    sudo -u postgres psql -d docreview -c "..."   # так БЫЛО, руками
    python3 scripts/register-review-pack.py \\
        --pack /opt/docreview/data/review-packs/generic/1.0 \\
        --database-url "postgresql+psycopg://docreview:PASS@localhost/docreview"

Повторный запуск безопасен: существующая запись обновляется, а не двоится.
"""

import argparse
import sys
from pathlib import Path
from uuid import uuid4

import yaml
from sqlalchemy import create_engine, text

MANIFEST_NAMES = ("pack.yaml", "pack.yml", "manifest.yaml", "manifest.yml")


def read_manifest(pack_dir: Path) -> dict:
    """Идентичность пакета из его манифеста — источника истины."""
    manifest = next(
        (candidate for name in MANIFEST_NAMES
         if (candidate := pack_dir / name).is_file()),
        None,
    )
    if manifest is None:
        raise SystemExit(f"в {pack_dir} нет манифеста ({', '.join(MANIFEST_NAMES)})")
    with manifest.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise SystemExit(f"{manifest}: ожидался словарь")
    pack_key = data.get("id") or data.get("pack_key")
    version = data.get("version")
    if not pack_key or version is None:
        raise SystemExit(f"{manifest} не объявляет id/pack_key и version")
    return {
        "pack_key": str(pack_key),
        "version": str(version),
        "display_name": str(data.get("name") or pack_key),
        "document_type": "technical_specification",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", required=True,
                    help="каталог пакета внутри review-packs приложения")
    ap.add_argument("--database-url", required=True)
    ap.add_argument("--company-slug", default="default",
                    help="tenant, которому виден пакет")
    ap.add_argument("--packs-root", default=None,
                    help="корень каталога пакетов; локатор считается от него")
    args = ap.parse_args()

    pack_dir = Path(args.pack).resolve()
    if not pack_dir.is_dir():
        raise SystemExit(f"{pack_dir} — не каталог")
    manifest = read_manifest(pack_dir)

    # Локатор — путь ОТНОСИТЕЛЬНО корня пакетов: приложение резолвит его
    # у себя и отвергает всё, что уводит наружу.
    root = Path(args.packs_root).resolve() if args.packs_root else pack_dir.parent.parent
    try:
        locator = pack_dir.relative_to(root).as_posix()
    except ValueError:
        raise SystemExit(f"{pack_dir} лежит вне корня пакетов {root}")

    engine = create_engine(args.database_url)
    with engine.begin() as conn:
        company_id = conn.execute(
            text("SELECT id FROM companies WHERE slug = :slug"),
            {"slug": args.company_slug},
        ).scalar()
        if company_id is None:
            raise SystemExit(f"компания «{args.company_slug}» не найдена")

        existing = conn.execute(
            text("SELECT id FROM review_pack_references "
                 "WHERE company_id = :c AND pack_key = :k AND version = :v"),
            {"c": company_id, "k": manifest["pack_key"], "v": manifest["version"]},
        ).scalar()

        if existing:
            conn.execute(
                text("UPDATE review_pack_references "
                     "SET display_name = :n, document_type = :d, locator = :l, "
                     "    is_active = true "
                     "WHERE id = :id"),
                {"n": manifest["display_name"], "d": manifest["document_type"],
                 "l": locator, "id": existing},
            )
            action = "обновлён"
        else:
            conn.execute(
                text("INSERT INTO review_pack_references "
                     "(id, company_id, pack_key, version, display_name, "
                     " document_type, locator, is_active) "
                     "VALUES (:id, :c, :k, :v, :n, :d, :l, true)"),
                {"id": uuid4(), "c": company_id, "k": manifest["pack_key"],
                 "v": manifest["version"], "n": manifest["display_name"],
                 "d": manifest["document_type"], "l": locator},
            )
            action = "зарегистрирован"

    print(f"{action}: {manifest['pack_key']}/{manifest['version']} "
          f"«{manifest['display_name']}», локатор {locator}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
