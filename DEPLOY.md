# Развёртывание на сервере

Ставим демонстрационный контур: приложение (API, воркер, веб) + ядро анализа.
Написано под чистый Ubuntu 22.04/24.04. Всё, что ниже, выполняется под sudo.

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
DOCREVIEW_DATABASE_URL=sqlite:////opt/docreview/data/docreview.db
DOCREVIEW_ANALYSIS_TIMEOUT_SECONDS=600
ENV
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
ExecStart=/opt/docreview/src/apps/api/.venv/bin/python -m uvicorn docreview_api.main:app --host 127.0.0.1 --port 8000
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

```bash
cd /opt/docreview/src/apps/web
npm ci && npm run build          # результат в dist/
cp -r dist /opt/docreview/web
```

```nginx
server {
    listen 80;
    server_name _;
    client_max_body_size 55m;          # загрузка до 50 МБ

    root /opt/docreview/web;
    location / { try_files $uri /index.html; }
    location /api/ { proxy_pass http://127.0.0.1:8000; }
}
```

---

## Проверка после развёртывания

```bash
systemctl status docreview-api docreview-worker --no-pager
curl -s localhost:8000/debug/health
journalctl -u docreview-worker -n 50 --no-pager
```

Сквозной сценарий: загрузить `data/synth/synth_3.txt` через интерфейс,
дождаться результата, убедиться что замечания появились.

---

## Известные ограничения этого развёртывания

- **Аутентификации нет.** Открывать наружу без хотя бы basic-auth нельзя.
- **PDF не поддерживается.** Ядро читает `.docx` и текст; для PDF библиотеки
  в контуре нет, файл будет отбит понятной ошибкой.
- **`--model-config` приложение не передаёт** (в `AnalysisProcessRequest` поле
  не заполняется), поэтому ядро берёт конфиг рядом с собой. Когда это поправят
  в приложении, флаг начнёт работать и переопределит файл.
- **Автоудаление документов выключено** в текущей версии приложения: загруженные
  файлы и результаты хранятся бессрочно. Для демо приемлемо, для пилота нет.
- Первый запрос после простоя дольше: модель прогревается (`keep_alive`).
