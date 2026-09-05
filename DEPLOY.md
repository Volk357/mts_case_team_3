# Развёртывание на сервере

Ставим демонстрационный контур: приложение (API, воркер, веб) + ядро анализа.
Написано под Ubuntu 22.04/24.04, выполняется под root.

**Проверено на практике 4 сентября:** развёрнуто на машине, где уже работал другой
сервис на 80-м порту. Ниже — то, что реально сработало, включая грабли.

---

## Прежде чем начинать — три вопроса, без которых деплой бессмысленен

**1. Где будет модель.** Ядро анализа работает через локальную LLM
(`qwen3:30b-a3b`, Ollama). На сервере без видеокарты она не запустится.
Варианты, по убыванию удобства:

| Вариант | Что нужно | Риск |
|---|---|---|
| На сервере есть GPU (≥24 ГБ) | поставить Ollama, скачать модель | долгая первая загрузка модели |
| Сервер ходит в нашу машину с RTX 4090 | сетевой доступ до эндпоинта | демо зависит от домашнего канала |
| Модели нет | работает только детерминированный слой | 11 типов из 29, LLM-замечаний не будет |

Без ответа на этот вопрос развёрнутое приложение будет принимать документы
и возвращать `MODEL_UNAVAILABLE`.

**2. Чей это сервер и что на него можно загружать.** Если сервер арендованный
и стоит вне контура компании, загружать в него реальные внутренние документы
нельзя — требование кейса про закрытый контур относится не только к модели,
но и к данным. Для демонстрации это решается синтетическими документами
(`data/synth/`), они специально для этого и сделаны.

**3. Нужен ли внешний доступ.** Если да — минимум HTTPS и базовая
аутентификация: в приложении сейчас нет аутентификации пользователя,
`X-Actor-Key` это неперсональный ключ обратной связи, а не вход.

---

## Что разворачиваем

```
/opt/docreview/
  core/            ядро анализа (этот репозиторий: docreview.py, правила, review-packs)
  app/             приложение (apps/api)
  web/             собранный фронтенд (статика)
  data/            рабочие каталоги приложения (documents, runs, artifacts, sqlite)
  model-config.yaml   эндпоинт и имя модели
```

База данных — SQLite по умолчанию (`database_url` в настройках приложения).
Postgres для демонстрации не обязателен; если нужен — меняется одной переменной.

---

## Шаги

### 1. Система

```bash
apt update
apt install -y python3.12 python3.12-venv python3-pip git nginx
# node нужен только если фронтенд собираем на сервере
curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && apt install -y nodejs
```

### 2. Код

```bash
mkdir -p /opt/docreview && cd /opt/docreview
git clone <репозиторий> src
ln -s /opt/docreview/src core        # ядро лежит в корне репозитория
```

### 3. Ядро анализа

```bash
python3.12 -m venv /opt/docreview/core-venv
/opt/docreview/core-venv/bin/pip install requests pyyaml

# исполняемая обёртка: приложение вызывает ядро ОДНОЙ командой,
# «python script.py» в настройку не поместится
cat > /usr/local/bin/docreview <<'SH'
#!/bin/sh
exec /opt/docreview/core-venv/bin/python /opt/docreview/core/docreview.py "$@"
SH
chmod +x /usr/local/bin/docreview
```

Конфиг модели — рядом с ядром (ядро найдёт его сам, см. ниже про `--model-config`):

```bash
cat > /opt/docreview/core/model-config.yaml <<'YML'
base_url: http://<хост-с-моделью>:11434/api/chat
model: qwen3:30b-a3b
num_ctx: 32768
timeout: 900
YML
chmod 600 /opt/docreview/core/model-config.yaml
```

Проверка ядра до всякого приложения:

```bash
docreview analyze --file /opt/docreview/core/data/synth/synth_3.txt \
  --run-id smoke --pack /opt/docreview/core/review-packs/mts-net/0.2 \
  --output /tmp/smoke.json
echo $?          # 0 — всё хорошо; 5 — модель недоступна; 3 — документ; 4 — пакет
python3 -c "import json;d=json.load(open('/tmp/smoke.json'));print(d['status'],len(d.get('findings',[])))"
```

### 4. Приложение

```bash
cd /opt/docreview/src/apps/api
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install --no-deps --no-build-isolation -e .

mkdir -p /opt/docreview/data
cat > /opt/docreview/app.env <<'ENV'
DOCREVIEW_ANALYSIS_EXECUTABLE=/usr/local/bin/docreview
DOCREVIEW_ANALYSIS_MODEL_CONFIG_PATH=/opt/docreview/core/model-config.yaml
DOCREVIEW_DATABASE_URL=sqlite:////opt/docreview/data/docreview.db
DOCREVIEW_DOCUMENTS_DIR=/opt/docreview/data/documents
DOCREVIEW_RUNS_DIR=/opt/docreview/data/runs
DOCREVIEW_REVIEW_PACKS_DIR=/opt/docreview/data/review-packs
DOCREVIEW_ANALYSIS_TIMEOUT_SECONDS=600
DOCREVIEW_WORKER_STALE_AFTER_SECONDS=900
ENV

# миграции до первого запуска
cd /opt/docreview/src/apps/api && set -a && . /opt/docreview/app.env && set +a
.venv/bin/python -m alembic upgrade head
```

`ANALYSIS_TIMEOUT_SECONDS` поднят: один документ обрабатывается около 40 секунд,
но на слабой сети до модели бывает дольше, а значение по умолчанию 300.

Каталог пакетов правил приложение ищет у себя; положим наш пакет туда, куда оно
смотрит, и засеем запись в базе с тем же ключом и версией (`mts-net` / `0.2`) —
иначе результат ядра будет забракован как несоответствующий заданию.

### 5. Службы

```bash
cat > /etc/systemd/system/docreview-api.service <<'UNIT'
[Unit]
Description=DocReview API
After=network.target

[Service]
User=docreview
WorkingDirectory=/opt/docreview/src/apps/api
EnvironmentFile=/opt/docreview/app.env
ExecStart=/opt/docreview/src/apps/api/.venv/bin/python -m uvicorn docreview_api.main:app --host 127.0.0.1 --port 8010
Restart=on-failure

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/docreview-worker.service <<'UNIT'
[Unit]
Description=DocReview worker
After=docreview-api.service

[Service]
User=docreview
WorkingDirectory=/opt/docreview/src/apps/api
EnvironmentFile=/opt/docreview/app.env
ExecStart=/opt/docreview/src/apps/api/.venv/bin/python -m docreview_api.workers.review_worker
Restart=on-failure

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now docreview-api docreview-worker
```

### 6. Фронтенд и nginx

**Собирать локально, а не на сервере.** На двух ядрах и 4 ГБ `vite build` рискует
уйти в OOM, а `node_modules` займёт сотни мегабайт. И ещё: если путь к проекту
содержит пробел, сборка падает (`Inbox mac` превращается в `Inbox%20mac`) —
копируйте в каталог без пробелов.

```bash
# локально, в каталоге без пробелов
(cd contracts && npm ci) && (cd apps/web && npm ci && npm run build)
rsync -az apps/web/dist/ root@СЕРВЕР:/opt/docreview/web/
```

Если на 80-м порту уже что-то работает, ставим DocReview на отдельный порт
и НЕ трогаем чужой конфиг. Перед каждым `reload` — обязательный `nginx -t`
и копия `sites-available`.

```nginx
server {
    listen 8080;
    server_name _;

    auth_basic "DocReview";                       # аутентификации в приложении нет
    auth_basic_user_file /etc/nginx/.docreview_htpasswd;
    client_max_body_size 55m;          # загрузка до 50 МБ

    root /opt/docreview/web;
    location / { try_files $uri /index.html; }
    location /api/ { proxy_pass http://127.0.0.1:8010; proxy_read_timeout 700s; }
}
```

---

## Проверка после развёртывания

```bash
systemctl status docreview-api docreview-worker --no-pager
curl -s localhost:8010/api/health   # именно /api/health
journalctl -u docreview-worker -n 50 --no-pager
```

Сквозной сценарий через API (интерфейс пока показывает только загрузку):

```bash
PACK=$(curl -s localhost:8010/api/review-packs | python3 -c 'import json,sys;print(json.load(sys.stdin)["items"][0]["review_pack_id"])')
DOC=$(curl -s -X POST localhost:8010/api/documents -F "document=@файл.docx" | python3 -c 'import json,sys;print(json.load(sys.stdin)["document_id"])')
KEY=$(python3 -c 'import uuid;print(uuid.uuid4())')
RID=$(curl -s -X POST localhost:8010/api/reviews -H "Content-Type: application/json" \
      -H "Idempotency-Key: $KEY" -d "{\"document_id\":\"$DOC\",\"review_pack_id\":\"$PACK\"}" \
      | python3 -c 'import json,sys;print(json.load(sys.stdin)["review_id"])')
curl -s localhost:8010/api/reviews/$RID        # статус
curl -s localhost:8010/api/reviews/$RID/findings
```

Ожидаемое время: около 40 секунд на документ при локальной модели,
65–80 секунд, если модель за туннелем.

---

## Грабли, на которые мы наступили

- **Хеш документа.** Приложение сверяет `document.sha256` из результата с хешем
  ЗАГРУЖЕННОГО ФАЙЛА. Ядро раньше считало хеш извлечённого текста: на `.txt`
  совпадало случайно, на `.docx` — никогда, и результат браковался целиком
  (`ReviewResultProjectionError`). Исправлено в ядре, но если увидите
  `WORKER_EXECUTION_ERROR` при успешном `result.json` — смотрите сюда.
- **Настройки валидируются взаимно.** `worker_stale_after_seconds` обязан быть
  больше `analysis_timeout_seconds` плюс grace, иначе приложение не стартует
  с невнятной ошибкой pydantic.
- **Пути в настройках по умолчанию** отсчитываются от корня репозитория,
  вычисленного относительно пакета. Если раскладка на сервере другая, задавайте
  `DOCREVIEW_DOCUMENTS_DIR`, `DOCREVIEW_RUNS_DIR`, `DOCREVIEW_REVIEW_PACKS_DIR` явно.
- **Review Pack надо засеять в базу** с тем же `pack_key`/`version`, что в манифесте
  пакета, иначе результат ядра будет отвергнут как несоответствующий заданию.
- **API живёт под префиксом `/api`**: `/api/health`, `/api/docs`. На `/debug/health`
  будет 404.
- **`POST /api/reviews` требует заголовок `Idempotency-Key`**, поле загрузки
  называется `document`, а не `file`.
- **Ядро запускается одной командой** — в настройку `analysis_executable` нельзя
  положить «python скрипт.py», нужна исполняемая обёртка.

## Известные ограничения этого развёртывания

- **Аутентификации нет.** Открывать наружу без хотя бы basic-auth нельзя.
- **PDF не поддерживается.** Ядро читает `.docx` и текст; для PDF библиотеки
  в контуре нет, файл будет отбит понятной ошибкой.
- **`--model-config` передаётся worker явно** из
  `DOCREVIEW_ANALYSIS_MODEL_CONFIG_PATH`. Файл должен существовать на хосте
  worker и не должен попадать в Git или журналы.
- **Автоудаление документов выключено** в текущей версии приложения: загруженные
  файлы и результаты хранятся бессрочно. Для демо приемлемо, для пилота нет.
- Первый запрос после простоя дольше: модель прогревается (`keep_alive`).
