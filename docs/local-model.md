# Локальная модель Михаила

## Подключение

Модель доступна только через WireGuard-туннель Михаила. VPN-профиль является
локальным секретом: его нельзя добавлять в Git, документацию, логи или артефакты
запуска.

| Параметр | Значение |
|---|---|
| Base URL | `http://10.0.0.8:11434` |
| OpenAI-compatible endpoint | `/v1/chat/completions` |
| Model | `qwen3:30b-a3b` |
| Runtime | Ollama на RTX 4090, модель целиком в GPU |

## Проверка доступности

```powershell
Invoke-RestMethod http://10.0.0.8:11434/api/tags
```

Ожидаемый результат — JSON со списком моделей, содержащим `qwen3:30b-a3b`.
Доступность `/api/tags` была подтверждена 3 сентября 2026 года.

## Обязательные параметры запроса

Контекст на сервере ограничен 4096 токенами. Analysis Core должен указывать
`options.num_ctx` в каждом запросе и не передавать значение больше 4096.

Для получения чистого JSON необходимо отключать рассуждение Qwen3 через
`"think": false`.

Минимальное тело запроса:

```json
{
  "model": "qwen3:30b-a3b",
  "messages": [
    {
      "role": "user",
      "content": "Проверь документ и верни JSON."
    }
  ],
  "stream": false,
  "think": false,
  "options": {
    "num_ctx": 4096
  }
}
```

При использовании OpenAI SDK нестандартные поля передаются через `extra_body`:

```python
response = client.chat.completions.create(
    model="qwen3:30b-a3b",
    messages=messages,
    extra_body={
        "think": False,
        "options": {"num_ctx": 4096},
    },
)
```

URL и имя модели относятся к development/demo-контуру и должны находиться в
конфигурации, а не быть захардкожены в Analysis Core или Product Application.
