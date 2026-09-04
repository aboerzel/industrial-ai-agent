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
Tools an und führt einen expliziten sequenziellen Tool Loop aus. Er validiert und
dispatcht einen Call pro LLM-Entscheidung, erhält strukturierte Observations im aktuellen
Conversation Context und erlaubt höchstens drei erfolgreich ausgeführte Tools pro Run.
Eine finale Modellantwort liefert strukturiertes `SUCCESS`; ein weiterer Tool-Wunsch
nach dem dritten Result liefert `LIMIT_REACHED`, ohne diesen Call auszuführen oder das
LLM erneut aufzurufen. Es existieren weder Agent-Framework, dynamische Tool Registry,
persistentes Memory noch Context Compression.

Es stehen zwei deterministische Eval-Baselines bereit. Die erste misst anhand von zwölf
versionierten Fällen die initiale LLM-Tool-Auswahl und Argumentextraktion des Agenten,
ohne Tools auszuführen. Die zweite führt zehn vollständige Agent Runs aus und vergleicht
die tatsächlichen begrenzten Trajectories und Termination Status mit strukturierter
Ground Truth. Keine der beiden Baselines bewertet die natürlichsprachliche Qualität der
finalen Antwort.

Eine isolierte `DocumentationSearchCapability.search_documentation(query)` durchsucht
jetzt eine kleine versionierte lokale technische Knowledge Base über einen inneren
`KnowledgeRetriever`-Port. Zwei deterministische lexical In-Memory-Adapter bieten
einfaches Term-Overlap- und rarity-aware IDF-Ranking. Die Results erhalten Document-,
Source-, Chunk-, Score- und Metadata-Provenance. Retrieval ist bewusst noch nicht als
Tool des `TroubleshootingAgent` exponiert.

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

Das erste Skript prüft die grundlegende LLM-Verbindung. Das zweite führt eine
mehrstufige Troubleshooting-Anfrage aus und prüft strukturell die sequenziellen Calls
`get_product_history(P4711)` und `get_machine_status(S04)` vor einer erfolgreichen
finalen Antwort.

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

## Manueller Trajectory-Eval

Führe das versionierte Multi-Step-Dataset durch den vollständigen begrenzten Agent Loop
aus:

```powershell
python -m evals.run_trajectory --profile troubleshooting
```

Der JSON Report enthält pro Fall erwartete und tatsächliche Trajectories,
Tool-Call-Anzahlen, Task Success Rate, Exact Trajectory Accuracy, Tool Call Accuracy und
Termination Accuracy. Die exakten Scoring-Formeln und ihre Interpretation beschreibt
die [Troubleshooting-Trajectory-Evaluation](docs/learning/trajectory-evaluation.de.md).

## Manueller Retrieval-Eval

Führe die eingefrorene v2-Retrieval-Baseline gegen beide unveränderten lokalen
Strategien aus:

```powershell
python -m evals.run_retrieval --dataset evals/datasets/knowledge_retrieval_v2.jsonl --strategy simple
python -m evals.run_retrieval --dataset evals/datasets/knowledge_retrieval_v2.jsonl --strategy idf
```

Der JSON Report enthält Hit@1, Hit@3, Mean Recall@3, erwartete und tatsächliche
Chunk-IDs pro Fall, explizite Fehlerlisten und Metriken pro Kategorie. Das ursprüngliche
v1-Dataset bleibt durch explizite Auswahl von `knowledge_retrieval_v1.jsonl` verfügbar.
Chunking- und Scoring-Formeln, den Vergleich von v1 und v2, die Freeze-Regel sowie
bekannte Grenzen beschreibt die
[lokale Knowledge-Retrieval-Baseline](docs/learning/knowledge-retrieval-baseline.de.md).

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

knowledge_base/
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
