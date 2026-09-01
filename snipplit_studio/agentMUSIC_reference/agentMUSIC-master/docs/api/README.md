# agentMUSIC API

The canonical OpenAPI schema is stored in [`../openapi.json`](../openapi.json).

When the backend is running, FastAPI also exposes:

- Swagger UI: `/docs`
- ReDoc: `/redoc`
- Raw OpenAPI JSON: `/openapi.json`

Regenerate the checked-in schema after API changes:

```bash
python3 scripts/export_openapi.py
```
