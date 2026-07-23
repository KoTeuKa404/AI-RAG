# Company Brain — корпоративна AI-база знань

Ця версія перетворює базовий RAG-сервіс на демонстраційний корпоративний продукт. Головний акцент — не лише генерація відповіді, а керування доступом, вимірювання якості та безпечна інтеграція з бізнес-системами.

## Ролі

- `owner` — повний доступ до workspace;
- `admin` — керування документами, ACL та аналітикою;
- `editor` — завантаження і видалення доступних документів;
- `viewer` — пошук і оцінювання власних відповідей.

Старий формат `{"api-key":"workspace"}` підтримується і трактується як owner-доступ, тому наявні локальні конфігурації не ламаються.

## Груповий доступ до документів

Документ може мати один із режимів:

- `workspace` — доступний усім ключам поточного workspace;
- `restricted` — доступний лише owner/admin або ключам із відповідною групою.

ACL застосовується в усіх критичних місцях: список документів, отримання документа, видалення, вибір конкретного документа в chat endpoint та загальний retrieval по chunks.

Приклад зміни доступу:

```http
PATCH /api/v1/documents/{document_id}/access
X-API-Key: ADMIN_KEY
Content-Type: application/json

{
  "visibility": "restricted",
  "allowed_groups": ["hr", "management"]
}
```

## Feedback loop

Кожна відповідь повертає `chat_id`. Клієнт може зберегти оцінку:

```http
PUT /api/v1/chat/{chat_id}/feedback
X-API-Key: USER_KEY
Content-Type: application/json

{
  "rating": 5,
  "comment": "Відповідь містить правильне посилання на політику"
}
```

Звичайний користувач може оцінювати лише відповіді, створені його API identity. Admin та owner можуть працювати з усім workspace.

## Бізнес-аналітика

`GET /api/v1/analytics/summary?days=30` повертає:

- кількість документів за статусами;
- кількість запитів;
- кількість активних API identities;
- середню оцінку;
- feedback coverage.

Ці показники дозволяють говорити про реальний ефект впровадження: adoption, якість відповідей і частку запитів, для яких користувачі залишили оцінку.

## Безпека

- workspace ніколи не береться з request body;
- API-ключ порівнюється через constant-time comparison;
- SQL retrieval завжди містить workspace та ACL predicates;
- restricted document не розкривається через duplicate upload message;
- production mode відмовляється запускатися з placeholder secrets;
- provider-specific LLM поле `reasoning_effort` вимкнене за замовчуванням;
- CI перевіряє lint, format, tests, compile та Docker build.
