# AMORCE Prospector — Instructions Claude Code

## Stack technique
- Python 3.11+
- FastAPI + uvicorn
- Playwright async (scraping)
- aiosqlite (SQLite async)
- Anthropic SDK async (claude-haiku-4-5-20251001)
- httpx async
- pytest + pytest-asyncio + pytest-mock

## Règles absolues de développement

### Code
- Tout le code async/await, jamais de code bloquant dans les coroutines
- Type hints obligatoires sur toutes les fonctions
- Docstrings courtes sur chaque fonction publique
- Pas de print() — uniquement logging avec getLogger(__name__)
- Jamais de bare except: — toujours capturer l'exception précise
- Constantes dans config.py, jamais hardcodées dans les modules

### Tests
- Chaque fonction publique a au moins un test
- Jamais de vrais appels réseau dans les tests (tout mocké)
- Jamais de vraie API LLM dans les tests (tout mocké)
- Fixtures dans conftest.py uniquement
- Un test = une seule assertion logique
- Nommer les tests : test_[fonction]_[condition]_[résultat_attendu]

### Gestion d'erreurs
- Toutes les fonctions qui appellent réseau ou LLM retournent
  un résultat dégradé en cas d'erreur, elles ne lèvent jamais
  d'exception vers l'appelant
- Logger l'erreur avant de retourner le fallback

### Avant de terminer chaque module
1. Lancer pytest sur le fichier de test correspondant
2. Vérifier qu'aucun import ne casse : python -c "import module"
3. Vérifier les types avec : pyright module.py (si disponible)


### pour lancer : .venv\Scripts\uvicorn main:app --reload --port 8000                
