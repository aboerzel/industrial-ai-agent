# ADR-010: Migration der Orchestrierung zu LangGraph und LangChain

## Status

Accepted

## Kontext

ADR-004 führte den Troubleshooting Loop bewusst als expliziten Python-Code ein. Diese
Implementierung machte Tool Calling, State Progression, deterministischen Dispatch,
Loop-Limits, Terminierung und Evaluation sichtbar und testbar. Sie hat diesen Lernzweck
erfüllt und bleibt eine nützliche Verhaltensreferenz.

Weitere Eigenimplementierung von Standardmechanismen der Graph-Orchestrierung bietet
inzwischen weniger Wert als das Erlernen und Anwenden etablierter produktionsorientierter
Agent-Technologie. LangGraph stellt expliziten State, Nodes, Edges, Conditional Routing
und einen Entwicklungspfad zu Durable Execution bereit. LangChain bietet standardisierte
Integrationsbausteine für Modelle, Messages, Tools und strukturierte Daten.

Die Einführung dieser Frameworks verändert eine langlebige Orchestrierungsgrenze und
führt Runtime Dependencies ein. Sie muss daher durch eine ADR geregelt werden und ist
kein lokales Refactoring. Die Migration muss Hexagonal Architecture, deterministische
Security Controls, Model Routing, Domain Capabilities und Eval-Baselines aus ADR-002,
ADR-003, ADR-005, ADR-008 und ADR-009 erhalten.

## Entscheidung

### Inkrementelle parallele Migration

Die Troubleshooting-Orchestrierung wird schrittweise zu LangGraph migriert. Der
bestehende handgeschriebene `TroubleshootingAgent` bleibt als manueller Referenzpfad
verfügbar, während parallel ein `LangGraphTroubleshootingAgent` eingeführt wird. Der
manuelle Pfad wird erst entfernt, wenn deterministische Tests und modellabhängige Evals
eine ausreichende funktionale Äquivalenz zeigen.

ADR-010 supersediert nur die Entscheidung aus ADR-004, den Orchestrierungsmechanismus
vollständig handgeschrieben zu halten, sowie die damalige Zurückstellung eines Agent
Frameworks. Die Verhaltensgarantien aus ADR-004 bleiben bindend: ein Tool Call pro
Modellentscheidung, deterministische Validierung und Dispatch, höchstens drei
ausgeführte Tools, eine letzte Modellentscheidung nach dem dritten Tool und keine
Ausführung eines angeforderten vierten Tools.

### Verantwortlichkeiten von LangGraph

LangGraph darf die Orchestrierungsmechanismen des parallelen Pfads übernehmen:

* typisierter Graph State
* Model- und Tool-Nodes
* feste und bedingte Edges
* der sequenzielle Agent Loop
* Tool-Execution-Flow
* deterministischer Termination-Flow

Der erste Migrations-Slice ergänzt weder Checkpointing, Persistenz, Durable Execution,
Human Approval noch Resume after Interruption. Diese Fähigkeiten erfordern spätere
Evidenz und, falls sie Architekturgrenzen verändern, spätere Entscheidungen.

### Verantwortlichkeiten von LangChain

LangChain Core darf gezielt verwendet werden für:

* Chat-Message-Repräsentationen an der Orchestrierungsgrenze
* Tool-Definitionen und Argument-Schemas
* Model-/Tool-Call-Integration
* Structured Outputs, sobald ein implementierter Use Case sie benötigt

LangChain wird nicht als anwendungsweites Framework eingeführt. Framework-Typen dürfen
im LangGraph-Orchestrierungspfad und seinen Integrationsadaptern existieren, aber nicht
in Domain Models, Repository Ports, Capability Contracts, Security Policy,
Retrieval-Ports oder Eval Ground Truth durchsickern.

### Projekteigene Verantwortlichkeiten

Folgende Bestandteile bleiben eigene Projektarchitektur und werden nicht an
Framework-Defaults delegiert:

* Domain Models und Invarianten
* Repository Ports
* Tool- und Capability-Semantik
* Tool-Name- und Argumentvalidierung
* deterministische Regeln für sequenziellen Dispatch und Limits
* `DataClassification` und `ExecutionZone`
* `ModelEgressPolicy` und die finale Pre-Adapter-Egress-Grenze
* `TaskRequirements` und `DeterministicModelRouter`
* semantische Model Profiles
* Retrieval-Ports und Provenance
* Eval-Datasets, Ground Truth und deterministisches Scoring

Framework-Convenience-APIs dürfen nur verwendet werden, wenn ihr Verhalten diese Regeln
erhält. Insbesondere dürfen Framework-Defaults für parallele Tool Calls, Retries,
Fallbacks oder Fehlerkonvertierung ADR-004, ADR-008 oder ADR-009 nicht stillschweigend
abschwächen.

### Security und Model Routing

ADR-009 bleibt vollständig bindend. Jeder Model Request aus dem Graph muss den
bestehenden finalen Egress-kontrollierten `LLMClient`-Pfad durchlaufen, bevor ein Provider
Adapter aufgerufen wird. LangGraph und LangChain dürfen weder Provider Clients direkt
konstruieren noch Fallback-Modelle wählen, Egress autorisieren oder sensitive Prompts,
Tool Results, Retrieval Results oder Traces an einen nicht freigegebenen externen Dienst
senden.

ADR-008 bleibt ebenfalls bindend. Eine Composition Root erzeugt explizite Task
Requirements, wendet Security Eligibility über `DeterministicModelRouter` an und
injiziert das ausgewählte semantische Model Profile in den Graph-Pfad. Der Graph
konstruiert keinen Router und wählt weder konkreten Provider noch konkretes Modell.

### Tool-Grenze

Der initiale Graph exponiert genau die bestehenden Capabilities:

* `get_product_history`
* `get_machine_status`

LangChain-Tool-Objekte sind Adapter über diesen Capabilities. Sie besitzen keine
Domain-Logik, Repositories, Provider-Konfiguration oder Security-Entscheidungen.
Tool-Argumente bleiben vor dem Capability-Aufruf deterministisch validiert, und der
initiale Graph führt pro Modellschritt höchstens ein angefordertes Tool aus.

### State-Grenze

Graph State enthält ausschließlich Orchestrierungsdaten: Conversation Messages,
Executed-Tool Count, normalisierte Executed-Tool-Datensätze, Run Status und Final-Answer-
State. Das ausgewählte Profile darf über das Graph-Objekt oder expliziten Invocation
Context injiziert werden, statt Provider-Konfiguration im State zu serialisieren. Domain
Entities und Infrastructure-SDK-Objekte werden nicht nur aus Bequemlichkeit im Graph
State gespeichert.

### Model-Integrationsgrenze

Der Graph-Pfad verwendet weiterhin den providerunabhängigen `LLMClient`. Ein kleiner
LangChain-kompatibler Adapter darf LangChain Messages und Tool Contracts in die
bestehenden internen `LLMRequest`-/`LLMResponse`-Modelle übersetzen. Er gehört an die
Orchestrierungs- und Infrastructure-Integrationsgrenze und muss den injizierten
Egress-geprüften Client aufrufen.

Der Graph darf `ChatOpenAI`, Ollama, Groq oder einen anderen providerspezifischen Client
nicht direkt instanziieren. Es gibt eine Model-Profile-Konfiguration und eine Egress
Policy, kein paralleles Framework-spezifisches Konfigurationssystem.

### Evaluation und Removal Gate

ADR-005 gilt. Beide Pfade verwenden dieselben versionierten First-Decision- und
Trajectory-Datasets sowie dieselben deterministischen Scorer. Die Identität interner
Framework Messages ist nicht Teil der Äquivalenz. Relevante Vergleiche sind:

* ausgewähltes Tool und Argumente
* ausgeführte Tool-Sequenz
* Tool-Call Count
* Result Status und Terminierung
* Vorhandensein einer finalen Antwort
* identisches Security- und Egress-Enforcement

Die manuelle Orchestrierung darf erst in einer separaten Änderung entfernt werden,
nachdem:

* deterministische Unit Tests für beide Pfade bestehen
* First-Decision-Evals keine inakzeptable Regression zeigen
* Trajectory-Evals keine inakzeptable Regression zeigen
* relevante lokale und explizite öffentliche Smoke Tests bestehen
* ein abgelehnter Model Request in keinem Pfad den Provider Adapter erreicht
* Tool-Sequenzen, Limits und Terminierung ausreichend äquivalent sind

### Scope und Nicht-Entscheidungen

Diese ADR wählt oder implementiert nicht:

* ein LangGraph-Persistenz- oder Checkpoint-Backend
* einen externen State Store
* LangSmith oder eine andere Tracing-Plattform
* MCP
* Multi-Agent-Orchestrierung
* Planner/Executor-Architektur
* Distributed Execution oder Queues
* Dynamic Tool Discovery
* Semantic- oder Hybrid-Retrieval-Integration
* Graph Subgraphs
* automatisches Model Routing, Eskalation, Retry oder Fallback

## Alternativen

### 1. Den handgeschriebenen Loop dauerhaft beibehalten

Als alleiniger zukünftiger Pfad abgelehnt. Dies erhält Transparenz, verwendet aber
weiterhin Projektaufwand für Standard-Orchestrierungsmechanismen und baut keine
praktische LangGraph-/LangChain-Erfahrung auf.

### 2. Den manuellen Pfad sofort ersetzen

Abgelehnt. Ein Big-Bang-Ersatz würde die Verhaltensreferenz entfernen, bevor Tests und
Evals Äquivalenz zeigen, und Framework-spezifische Regressionen schwerer isolierbar
machen.

### 3. Parallelen LangGraph-Pfad mit begrenzter LangChain-Nutzung einführen

Gewählt. Dies erlaubt direkten Vergleich, hält deterministische Policies in
Projektverantwortung und validiert die Framework-Einführung vor dem Entfernen des
Referenzpfads.

### 4. Einen High-Level-Prebuilt-Agent für die gesamte Orchestrierung verwenden

Für die initiale Migration abgelehnt. Framework-Defaults können parallele Calls,
Retries oder eine von ADR-004 abweichende Terminierung erlauben und die expliziten
Security- und Routing-Grenzen verbergen.

### 5. Domain, Tools, Routing und Security in LangChain-Abstraktionen verschieben

Abgelehnt. Dadurch würde Integrationstechnologie Domain- und Application-Architektur
dominieren, Provider-Unabhängigkeit schwächen und kritische deterministische Policies
von Framework-Verhalten abhängig machen.

## Konsequenzen

Positiv:

* das Projekt gewinnt praktische LangGraph- und LangChain-Erfahrung an einem bereits
  gemessenen Use Case
* Graph State und Control Flow werden explizite Framework-Konzepte, ohne Project Security
  oder Domain-Semantik zu verdecken
* Manual- und Graph-Pfad können mit unveränderten Evals verglichen werden
* zukünftiges Checkpointing und Interruption Support erhalten eine kompatible Basis
* Provider-, Routing- und Egress-Grenzen bleiben wiederverwendbar

Negativ:

* beide Orchestrierungspfade müssen vorübergehend gepflegt werden
* LangGraph und LangChain Core werden Runtime Dependencies
* Message- und Tool-Konvertierung führt eine zusätzliche Adaptergrenze ein
* Framework-Upgrades können Orchestrierungsverhalten beeinflussen und erfordern
  Regressionstests
* Äquivalenz ist verhaltensbezogen und keine Gleichheit interner State-Repräsentationen

## Beziehung zu bestehenden Entscheidungen

ADR-002 bleibt gültig: Die Graph-Orchestrierung verwendet `LLMClient` und semantische
Model Profiles statt konkreter Provider Clients. ADR-003 bleibt gültig:
Framework-Integration bleibt außerhalb der Domain und Infrastructure wird an Composition
Roots injiziert. ADR-005 liefert Tests und unveränderte Eval-Baselines. ADR-008 besitzt
deterministisches Model Routing. ADR-009 besitzt Security Eligibility und finales
Pre-Adapter-Egress-Enforcement.

ADR-010 supersediert ADR-004 nur teilweise bezüglich der gewählten
Orchestrierungstechnologie. Das begrenzte sequenzielle Verhalten und die
deterministischen Garantien aus ADR-004 bleiben während der Migration der verbindliche
Vertrag.
