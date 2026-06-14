# AMORCE Prospector

Outil de prospection automatisée pour AMORCE, agence IA basée à Casablanca. Il visite des sites d'entreprises marocaines, détecte leurs besoins IA, génère un score de qualification et rédige un email de prospection personnalisé.

## Prérequis

- Python 3.11+
- Clé API Anthropic (obligatoire pour la rédaction des emails)
- Ollama (optionnel, pour la qualification locale sans coût API)

## Installation

```bash
git clone <url-du-repo>
cd amorce-prospector
chmod +x setup.sh && ./setup.sh
```

Puis éditer `.env` pour ajouter votre clé API :

```bash
ANTHROPIC_API_KEY=sk-ant-...
```

## Lancement

```bash
source venv/bin/activate
uvicorn main:app --reload --port 8000
```

Ouvrir [http://localhost:8000](http://localhost:8000)

## Utilisation

1. Coller des URLs dans la zone de texte (1 par ligne, max 50)
2. Cliquer **Lancer la prospection**
3. Suivre l'analyse en temps réel (scraping → qualification → email)
4. Consulter le tableau des prospects qualifiés
5. Cliquer **✉️ Email** pour voir et copier l'email généré
6. Cliquer **📥 Exporter CSV** pour télécharger tous les prospects

## Variables d'environnement (`.env`)

| Variable | Obligatoire | Défaut | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Oui | — | Clé API Anthropic pour la rédaction des emails |
| `OLLAMA_BASE_URL` | Non | `http://localhost:11434` | URL du serveur Ollama local |
| `OLLAMA_MODEL` | Non | `llama3` | Modèle Ollama à utiliser pour la qualification |
| `DB_PATH` | Non | `amorce.db` | Chemin vers la base SQLite |
| `MAX_CONCURRENT_SCRAPES` | Non | `3` | Nombre de scrapes en parallèle |
| `SCRAPE_TIMEOUT` | Non | `15` | Timeout (secondes) par scrape |
| `LOG_LEVEL` | Non | `INFO` | Niveau de log (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

## Architecture

```
main.py          → API FastAPI + WebSocket (temps réel)
scraper.py       → Playwright (headless) + httpx (fallback)
qualifier.py     → Règles heuristiques + Ollama → Claude (fallback)
email_writer.py  → Génération email via Claude Haiku
database.py      → Persistance SQLite async (aiosqlite)
models.py        → Modèles Pydantic v2
config.py        → Constantes centralisées
static/          → Interface web vanilla (HTML/CSS/JS)
```

## Pipeline de traitement

```
URL → scrape_website() → qualify_prospect() → write_prospecting_email() → DB
                          ↓ Ollama (local)       ↓ Claude Haiku
                          ↓ Claude (fallback)
```

Scoring : **3 étoiles** = chatbot ou catalogue détecté (priorité haute) · **2 étoiles** = service client + formulaire · **1 étoile** = GEO uniquement

## Tests

```bash
# Tests unitaires + intégration
pytest tests/ -v

# Avec couverture
pytest tests/ --cov=. --cov-report=term-missing

# Un seul module
pytest tests/test_scraper.py -v
```

Couverture actuelle : **97%** global · tous les modules ≥ 80%.
# Amorce-prospect
