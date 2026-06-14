# Instructions tests

## Toujours utiliser ces patterns

### Fixture DB temporaire
Utiliser tmp_path de pytest pour la DB SQLite de test.
Ne jamais utiliser la DB de production (amorce.db).

### Mocker les appels externes
- scraper.py → mocker playwright.async_api et httpx.AsyncClient
- qualifier.py → mocker _call_ollama et _call_claude séparément
- email_writer.py → mocker anthropic.AsyncAnthropic
- main.py → mocker scraper, qualifier, email_writer entièrement

### Pattern mock LLM standard
```python
mock_response = MagicMock()
mock_response.content = [MagicMock(text='{"score": 3, ...}')]
mock_client.messages.create = AsyncMock(return_value=mock_response)
```

### pytest.ini settings attendus
asyncio_mode = auto
testpaths = tests

## Commande de référence
pytest tests/ -v --tb=short --cov=. --cov-omit="tests/*,static/*"
