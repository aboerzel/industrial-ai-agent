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

Zwei deterministische Domain Capabilities sind implementiert: das Abrufen der
Produktionshistorie über `ProductHistoryCapability.get_product_history(product_id)` und
des aktuellen Maschinenstatus über
`MachineStatusCapability.get_machine_status(station_id)`. Beide verwenden innere
Repository-Ports mit deterministischen In-Memory-Adaptern. Zusätzlich stehen ein
provider-unabhängiger `LLMClient`-Port und ein OpenAI-compatible Infrastructure Adapter
bereit. Die Modellwahl verwendet das konfigurierte semantische Profil
`troubleshooting`. `TroubleshootingAgent` bietet dem Modell genau die zwei bekannten
Tools an, validiert und dispatcht höchstens einen ausgewählten Aufruf in
deterministischem Code und lässt das Modell die finale Antwort formulieren. Ein
allgemeiner Agent- oder ReAct-Loop existiert nicht.

Eine erste deterministische Eval-Baseline misst die initiale LLM-Tool-Auswahl und
Argumentextraktion des Agenten anhand von zwölf versionierten Fällen. Sie führt keine
Tools aus und bewertet keine finalen Antworten.

Es wurden noch kein LLM framework, MCP server, keine vector database und kein multi-agent framework eingeführt.

## Manuelle Ollama Smoke Tests

Der Smoke Test ist bewusst von den automatisierten Tests getrennt und ruft das
konfigurierte lokale Modell auf. Installiere und starte Ollama, stelle sicher, dass
`qwen3.5:9b` verfügbar ist, und führe Folgendes aus:

```powershell
ollama pull qwen3.5:9b
python scripts/smoke_test_ollama.py
python scripts/smoke_test_troubleshooting_agent.py
```

Das erste Skript prüft die grundlegende LLM-Verbindung. Das zweite führt den
vollständigen Tool-Selection-Slice aus und prüft sowohl `get_product_history` für das
Produkt `P4711` als auch `get_machine_status` für die Station `S12`.

## Manueller Tool-Selection-Eval

Führe das versionierte Tool-Selection-Dataset gegen das konfigurierte semantische Profil
aus:

```powershell
python -m evals.run_tool_selection --profile troubleshooting
```

Der Befehl gibt einen strukturierten JSON Report mit Einzelergebnissen, Tool Selection
Accuracy und Argument Accuracy aus. Definitionen und Interpretation der Metriken sowie
die optionale lokale Ergebnisausgabe beschreibt die
[Baseline für die Tool-Selection-Evaluation](docs/learning/tool-selection-evaluation.de.md).

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
