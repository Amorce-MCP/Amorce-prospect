#!/bin/bash
set -e

echo "=== Setup AMORCE Prospector ==="

python -m venv venv
source venv/bin/activate

pip install -r requirements.txt
pip install -r requirements-dev.txt

playwright install chromium

cp .env.example .env

echo "=== Vérification Ollama ==="
if command -v ollama &> /dev/null; then
  echo "✅ Ollama détecté"
else
  echo "⚠️  Ollama non installé (optionnel). Claude API sera utilisé."
  echo "   Pour installer : https://ollama.ai"
fi

echo "=== Lancement des tests ==="
pytest tests/ -v --tb=short

echo ""
echo "=== ✅ Setup terminé. Lance l'app avec : ==="
echo "   source venv/bin/activate && uvicorn main:app --reload"
