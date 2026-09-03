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

Nur die Projektgrundlage ist vorhanden.

Es wurden noch kein LLM framework, MCP server, keine vector database und kein multi-agent framework eingeführt.

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
