# Industrial AI Agent

Produktionsorientiertes Lern- und Portfolioprojekt für Agentic / Applied AI in einem industriellen Umfeld.

Das Projekt beginnt mit einfachen, expliziten Python-Bausteinen und entwickelt sich schrittweise in Richtung:

* LLM tool calling
* agent state und context management
* retrieval-augmented generation
* evaluations
* observability und tracing
* guardrails und human approval
* MCP-basierte Integrationen
* eine industrielle Multi-Service-AI-Architektur

## Aktueller Stand

Der erste deterministische vertikale Slice ist implementiert: das Abrufen der
Produktionshistorie über die agent-facing Capability
`ProductHistoryCapability.get_product_history(product_id)`, gestützt durch ein
In-Memory-Repository. Zusätzlich stehen ein provider-unabhängiger `LLMClient`-Port und
ein OpenAI-compatible Infrastructure Adapter bereit. Die Modellwahl verwendet das
konfigurierte semantische Profil `troubleshooting`; ein Agent Loop existiert noch nicht.

Es wurden noch kein LLM framework, MCP server, keine vector database und kein multi-agent framework eingeführt.

## Manueller Ollama Smoke Test

Der Smoke Test ist bewusst von den automatisierten Tests getrennt und ruft das
konfigurierte lokale Modell auf. Installiere und starte Ollama, stelle sicher, dass
`qwen3.5:9b` verfügbar ist, und führe Folgendes aus:

```powershell
ollama pull qwen3.5:9b
python scripts/smoke_test_ollama.py
```

Die committed Modellkonfiguration liegt in `config/model_profiles.toml`. Das lokale
Ollama-Profil benötigt keinen API Key. Authentifizierte Profile müssen Credential-Werte
aus Environment Variables oder der ignorierten lokalen `.env`-Datei lesen;
`.env.example` enthält keine geheimen Werte.

## Entwicklungsprinzipien

* Bevorzuge einfachen, expliziten Code.
* Verwende deterministischen Code für Garantien.
* Verwende LLMs für Beurteilungen und Entscheidungen.
* Führe Frameworks nur ein, wenn sie ein konkretes Problem lösen.
* Halte Tests und Dokumentation nah an der Implementierung.
* Behandle dieses Repository sowohl als Lernprojekt als auch als professionelles Referenzprojekt.

## Projektstruktur

```text
src/industrial_ai_agent/
├── agent/
├── domain/
├── infrastructure/
└── tools/

tests/
├── unit/
└── integration/

docs/
├── architecture/
├── decisions/
└── learning/

evals/
├── datasets/
└── results/
```

## Python

Python 3.12+

## Qualität

Die Entwicklung sollte Folgendes umfassen:

* type hints
* Pydantic an Systemgrenzen
* pytest
* Ruff
* fokussierte Commits
* Architecture Decision Records für wesentliche Entscheidungen
