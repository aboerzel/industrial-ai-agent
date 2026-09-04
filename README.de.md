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
bereit. Die Modellwahl verwendet explizite Task Requirements und den deterministischen
Model Router. Der handgeschriebene `TroubleshootingAgent` als Referenz und der parallele
`LangGraphTroubleshootingAgent` bieten genau dieselben zwei bekannten Tools an. Beide
erhalten die begrenzte sequenzielle Semantik: ein validierter und dispatchter Call pro
LLM-Entscheidung, erhalten strukturierte Observations im aktuellen Conversation Context
und erlauben höchstens drei erfolgreich ausgeführte Tools pro Run.
Eine finale Modellantwort liefert strukturiertes `SUCCESS`; ein weiterer Tool-Wunsch
nach dem dritten Result liefert `LIMIT_REACHED`, ohne diesen Call auszuführen oder das
LLM erneut aufzurufen. Der LangGraph-Pfad verwendet LangChain-Core-Messages und
Tool-Verträge über einen schmalen Adapter zum bestehenden Security-geprüften
`LLMClient`. Seine lokale/Test-HITL-Demonstration verwendet einen injizierten
In-Memory-Checkpointer; es existieren weder dynamische Tool Registry, dauerhaftes
Persistenz-Backend, LangSmith-Integration noch Context Compression.

Es stehen zwei deterministische Eval-Baselines bereit. Die erste misst anhand von zwölf
versionierten Fällen die initiale LLM-Tool-Auswahl und Argumentextraktion des Agenten,
ohne Tools auszuführen. Die zweite führt zehn vollständige Agent Runs aus und vergleicht
die tatsächlichen begrenzten Trajectories und Termination Status mit strukturierter
Ground Truth. Keine der beiden Baselines bewertet die natürlichsprachliche Qualität der
finalen Antwort.

Eine isolierte `DocumentationSearchCapability.search_documentation(query, top_k=3)` durchsucht
jetzt eine kleine versionierte lokale technische Knowledge Base über einen inneren
`KnowledgeRetriever`-Port. Drei deterministische lexical In-Memory-Adapter bieten
einfaches Term-Overlap-, rarity-aware IDF- und BM25-Ranking. Die Results erhalten
Document-, Source-, Chunk-, Score- und Metadata-Provenance. LangGraph erhält Retrieval
ausschließlich über `knowledge_mcp`, nie durch direkte Retriever-Injection.

Zwei schreibgeschuetzte MCP-Services adaptieren bestehende Capabilities über das
offizielle MCP SDK v2. `factory_mcp` exponiert `get_product_history` und
`get_machine_status`; `knowledge_mcp` exponiert `search_documentation`. Beide
unterstützen prozessgekoppeltes stdio für Entwicklung/Tests und Streamable HTTP an `/mcp`
für das Deployment. Der asynchrone LangGraph-Pfad entdeckt und autorisiert Tools aller
konfigurierten Server, weist doppelte Toolnamen zurück, öffnet pro Server eine Session
für den Run und ruft Tools sequenziell auf. Der direkte LangChain-Tool-Pfad bleibt
Referenz; es gibt keinen allgemeinen MCP Router und keine MCP Write Action.

## Manueller MCP-Smoke-Test

Fuehre den lokalen stdio-Client und -Server ohne LLM oder externen Service aus:

```powershell
python scripts/smoke_test_factory_mcp.py
python scripts/smoke_test_knowledge_mcp.py
python scripts/smoke_test_langgraph.py --confidential-troubleshooting --mcp
```

Die Server-Smokes geben Discovery und strukturierte Results aus. Der LangGraph-Smoke
verwendet für seinen vertraulichen Run ausschließlich `local_quality` und prüft
`get_product_history(P4711) -> get_machine_status(S04) -> search_documentation(...)`.

Um den Netzwerk-Deployment-Pfad auszuführen, baue und starte beide lokalen Services:

```powershell
docker compose up --build -d factory-mcp knowledge-mcp
python scripts/smoke_test_factory_mcp.py --transport http
python scripts/smoke_test_knowledge_mcp.py --transport http
python scripts/smoke_test_langgraph.py --confidential-troubleshooting --mcp --mcp-transport http
```

Factory startet standardmäßig an `0.0.0.0:8001` und Knowledge an `0.0.0.0:8002`; ihre
SDK-verwalteten Endpunkte sind `http://127.0.0.1:8001/mcp` und
`http://127.0.0.1:8002/mcp`. Beide Images laufen als Non-Root-User und enthalten weder
`.env` noch Secrets. Das Knowledge-Image enthält keine Modellartefakte: Compose nutzt den
Host-Ollama-Endpunkt für `qwen3-embedding:0.6b`, verwendet standardmäßig CPU für den
Reranker und mountet einen vorab gefüllten benannten Hugging-Face-Cache read-only. Fülle
ihn vor dem Start mit `hf download BAAI/bge-reranker-v2-m3` im Volume; lokale
In-Process-Ausführung wählt weiterhin CUDA, falls verfügbar. Docker deployt Prozesse,
MCP liefert Tool-Protokoll und Discovery. Die nicht authentifizierten HTTP-Endpunkte sind
nur für diese lokale Demo akzeptiert; Remote- oder Production-Deployment benötigt MCP
Authentication und Transport Security. MCP-Netzwerktransport autorisiert keinen Model
Egress: Vertrauliches Troubleshooting nutzt unter ADR-009 das lokale Profile; Knowledge-
Queries, Chunks, Embeddings und Reranker-Inputs erreichen nie `public_fast` oder einen
Public Provider.

Das aktuelle stabile Release von `langchain-mcp-adapters` (`0.3.2`) besitzt weiterhin
keine veröffentlichte MCP-SDK-v2-Unterstützung, deshalb bleibt die temporäre
projekteeigene Bridge bewusst erhalten.

## Manuelle Model-Profile-Smoke-Tests

Der Smoke Test ist bewusst von den automatisierten Tests getrennt. Sein Default-Aufruf
ruft ausschließlich die konfigurierten lokalen Modelle auf. Installiere und starte
Ollama, stelle sicher, dass beide Modelle verfügbar sind, und führe Folgendes aus:

```powershell
ollama pull qwen3.5:4b
ollama pull qwen3.5:9b
python scripts/smoke_test_ollama.py
python scripts/smoke_test_ollama.py --profile local_fast
python scripts/smoke_test_ollama.py --profile local_quality
python scripts/smoke_test_model_routing.py
python scripts/smoke_test_troubleshooting_agent.py
python scripts/smoke_test_langgraph.py --profile local_fast
python scripts/smoke_test_langgraph.py --profile local_quality
python scripts/smoke_test_langgraph.py --confidential-troubleshooting
python scripts/smoke_test_langgraph_hitl.py --approval approve
python scripts/smoke_test_langgraph_hitl.py --approval reject
```

Ohne `--profile` ruft das erste Skript `local_fast` und `local_quality` nacheinander auf.
Die expliziten Aufrufe testen jedes semantische Profile separat und geben sein
konfiguriertes Modell zusammen mit der Antwort aus. Der Router Smoke prüft
deterministisch eine kostenorientierte öffentliche Auswahl, eine vertrauliche lokale
Auswahl mit hoher Quality und Fail-closed bei einer vertraulichen Auswahl, wenn nur
`public_fast` verfügbar ist. Das Troubleshooting-Skript erstellt explizite vertrauliche
Task Requirements, wählt aktuell das kompatible lokale Profile `local_quality`, führt
eine mehrstufige Anfrage aus und prüft strukturell die sequenziellen Calls
`get_product_history(P4711)` und `get_machine_status(S04)` vor einer erfolgreichen
finalen Antwort.

Der HITL-Smoke führt den LangGraph-Pfad mit einem vertraulichen lokalen Profile und
einem In-Memory-Checkpointer aus. Er zeigt den strukturierten Approval Request für die
harmlose Demonstrations-Action `create_maintenance_ticket` und setzt denselben Thread
mit dem gewählten expliziten Result fort. Er ruft weder ein externes Ticket-System auf
noch führt er eine Machine Action aus.

Das Profile `public_fast` verwendet Groq über denselben
`OpenAICompatibleLLMClient`. Setze `GROQ_API_KEY` in der unversionierten lokalen
`.env`-Datei und rufe das Profile ausschließlich explizit auf:

```powershell
python scripts/smoke_test_ollama.py --profile public_fast
python scripts/smoke_test_langgraph.py --profile public_fast
```

Ausführbare Entry Points laden die `.env` im Project Root explizit als lokale Runtime-
Konfiguration. Bereits gesetzte Prozess-Environment-Variables haben Vorrang und werden
niemals durch Werte aus `.env` überschrieben.

Dieser Public-Cloud-Smoke-Pfad sendet ausschließlich den synthetischen Prompt
`Reply exactly with PUBLIC_LLM_OK` und klassifiziert ihn explizit als `PUBLIC`. Der
deterministische ADR-009-Egress-Check validiert die `PUBLIC_CLOUD` Execution Zone des
Profiles, bevor der Provider Adapter aufgerufen wird. `public_fast` wird weder
automatisch ausgewählt noch als Fallback Profile verwendet.

## Manueller Tool-Selection-Eval

Führe das unveränderte versionierte Tool-Selection-Dataset gegen beide
Orchestrierungspfade aus:

```powershell
python -m evals.run_tool_selection --agent-path manual --profile troubleshooting
python -m evals.run_tool_selection --agent-path langgraph --profile troubleshooting
python -m evals.run_tool_selection --agent-path langgraph --tool-transport mcp --profile troubleshooting
```

Der Befehl gibt einen strukturierten JSON Report mit Einzelergebnissen, Tool Selection
Accuracy und Argument Accuracy aus. Definitionen und Interpretation der Metriken sowie
die optionale lokale Ergebnisausgabe beschreibt die
[Baseline für die Tool-Selection-Evaluation](docs/learning/tool-selection-evaluation.de.md).

## Manueller Trajectory-Eval

Führe das unveränderte versionierte Multi-Step-Dataset durch beide vollständigen
begrenzten Agent-Pfade aus:

```powershell
python -m evals.run_trajectory --agent-path manual --profile troubleshooting
python -m evals.run_trajectory --agent-path langgraph --profile troubleshooting
python -m evals.run_trajectory --agent-path langgraph --tool-transport mcp --profile troubleshooting
```

Der JSON Report enthält pro Fall erwartete und tatsächliche Trajectories,
Tool-Call-Anzahlen, Task Success Rate, Exact Trajectory Accuracy, Tool Call Accuracy und
Termination Accuracy. Die exakten Scoring-Formeln und ihre Interpretation beschreibt
die [Troubleshooting-Trajectory-Evaluation](docs/learning/trajectory-evaluation.de.md).

## Manueller Retrieval-Eval

Führe die eingefrorene v2-Retrieval-Baseline gegen alle sechs lokalen Strategien aus:

```powershell
python -m evals.run_retrieval --dataset evals/datasets/knowledge_retrieval_v2.jsonl --strategy simple
python -m evals.run_retrieval --dataset evals/datasets/knowledge_retrieval_v2.jsonl --strategy idf
python -m evals.run_retrieval --dataset evals/datasets/knowledge_retrieval_v2.jsonl --strategy bm25
python -m evals.run_retrieval --dataset evals/datasets/knowledge_retrieval_v2.jsonl --strategy semantic
python -m evals.run_retrieval --dataset evals/datasets/knowledge_retrieval_v2.jsonl --strategy hybrid
python -m evals.run_retrieval --dataset evals/datasets/knowledge_retrieval_v2.jsonl --strategy reranked
python scripts/smoke_test_semantic_retrieval.py
python scripts/smoke_test_reranked_retrieval.py
```

Der JSON Report enthält Hit@1, Hit@3, Mean Recall@3, erwartete und tatsächliche
Chunk-IDs pro Fall, explizite Fehlerlisten und Metriken pro Kategorie. Das ursprüngliche
v1-Dataset bleibt durch explizite Auswahl von `knowledge_retrieval_v1.jsonl` verfügbar.
Chunking- und Scoring-Formeln, den Vergleich von v1 und v2, die semantische, hybride
und rerankte Baseline, die Freeze-Regel sowie
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
