# LangGraph- und LangChain-Orchestrierung

## Warum die Frameworks jetzt eingeführt werden

Der handgeschriebene `TroubleshootingAgent` hat die wesentlichen Mechanismen sichtbar
gemacht: Model Tool Calling, State Progression, deterministische Validierung und
Dispatch, begrenzte Iteration, Termination und Trajectory-Evaluation. Weitere
Standard-Orchestrierungsinfrastruktur selbst zu implementieren, bietet inzwischen
weniger Wert als das Erlernen eines produktionsrelevanten Graphmodells.

[ADR-010](../decisions/ADR-010-langgraph-and-langchain-orchestration-migration.de.md)
führt deshalb einen parallelen `LangGraphTroubleshootingAgent` ein. Der handgeschriebene
Agent bleibt die Verhaltensreferenz, bis deterministische Tests, unveränderte
Eval-Datasets und Live-Smokes ausreichende Äquivalenz zeigen.

## Graph State

`TroubleshootingGraphState` enthält ausschließlich Orchestrierungsdaten:

* LangChain Conversation Messages
* die Anzahl erfolgreich ausgeführter Tools
* normalisierte ausgeführte Tool Calls
* den Run Status
* eine optionale finale Antwort
* eine optionale Pending Action und ihr Approval Result
* den ausgewählten Profile-Namen und die explizite Run Classification für fortsetzbare Runs

Domain Entities und Repositories werden nicht zu Graph State. Ein Checkpoint-Run für
lokale Tests und Demonstrationen verwendet zusätzlich LangGraphs nativen
`InMemorySaver`; dies ist keine dauerhafte Persistenz.

## Nodes und Edges

Der Read-Only-Pfad besitzt zwei Nodes:

1. Der **Model Node** ruft das bereits ausgewählte Modell über den kontrollierten Client auf.
2. Der **Tool Node** validiert einen angeforderten Call, ruft eine bestehende Capability
   auf und hängt eine strukturierte Observation an.

`START` führt in den Model Node. Eine Conditional Edge leitet eine finale Antwort, einen
deterministischen Fehler oder ein ausgeschöpftes Budget zu `END`; genau ein gültiger
Tool Request führt zum Tool Node. Der Tool Node führt zurück zum Model Node. Dieser
Edge-Zyklus ist der Agent Loop.

Wenn die optionale Demonstrations-Capability `create_maintenance_ticket` injiziert ist,
ergänzt der Graph vier fokussierte Nodes. Der Action-Preparation-Node validiert und
speichert eine Pending Action ohne Side Effect. Der Approval Node ruft `interrupt()` mit
einem JSON-serialisierbaren `action_approval`-Payload auf. Ein genehmigter Resume führt
zum Action-Execution-Node; eine Ablehnung führt zum Cancellation-Node und beendet den
Run ohne Ausführung der Action.

## Tool Execution und Termination

LangChain-`StructuredTool`-Instanzen beschreiben `get_product_history` und
`get_machine_status`. Sie sind Adapter um bestehende Projekt-Capabilities, keine neuen
Orte für Domain-Logik. Ein eigener Tool Node erhält bewusst die One-Call-Validierung und
den sequenziellen Dispatch.

`MAX_TOOL_CALLS = 3` hat in beiden Agents dieselbe Bedeutung. Drei Tools dürfen
ausgeführt werden. Der folgende Modellschritt darf eine finale Antwort liefern; ein
vierter Request erzeugt `LIMIT_REACHED`, wird nicht ausgeführt und verursacht keinen
weiteren Model Call. Unbekannte Tools, ungültige Argumente und mehrere Calls bleiben
deterministische Fehler.

## Was LangChain bereitstellt

Dieser Slice hängt direkt von `langchain-core` für Message- und Tool-Verträge ab. Der
kleine Infrastructure Adapter `LLMClientChatModel` übersetzt diese Verträge in die
bestehenden provider-unabhängigen Request- und Response-Modelle von `LLMClient`. Er
erstellt keinen Provider, wählt kein Profile und definiert keine Security Policy.

Das vollständige LangChain Application Framework wird nicht übernommen. Structured
Output kann später verwendet werden, wenn eine implementierte Capability es benötigt.

## Was im Besitz des Projekts bleibt

Das Projekt verantwortet weiterhin:

* Domain Models, Invariants, Repositories und Capability-Semantik
* `DataClassification`, `ExecutionZone` und `ModelEgressPolicy`
* die finale `EgressCheckedLLMClient`-Grenze
* `TaskRequirements`, Profile Metadata und `DeterministicModelRouter`
* Tool-Budgets, Argumentvalidierung, Dispatch und Termination-Garantien
* Retrieval-Ports, Eval-Datasets, Ground Truth und deterministisches Scoring

Der Composition Root führt Security Eligibility und Task-Level Routing aus, bevor er
den Graph-Pfad konstruiert. Er injiziert das ausgewählte `ModelProfile` und einen
Egress-kontrollierten Client. LangGraph führt weder autonomes Model Routing noch
Fallback aus. Der finale Pre-Adapter-Egress-Check bleibt für jeden Model Call aktiv.

## Checkpointing und Human Approval

[ADR-011](../decisions/ADR-011-agent-persistence-and-human-in-the-loop.de.md) ergänzt
eine begrenzte Checkpoint- und Human-in-the-Loop-Demonstration ausschließlich im
LangGraph-Pfad. Der Graph wird mit LangGraphs nativem `InMemorySaver` kompiliert; ein
fortsetzbarer Aufruf verwendet `{"configurable": {"thread_id": "..."}}`. Die
`thread_id` identifiziert einen Graph Run; für `Command(resume="approve")` oder
`Command(resume="reject")` ist dieselbe ID erforderlich.

`InMemorySaver` eignet sich für deterministische Tests und lokale Demonstrationen,
verliert aber Checkpoints beim Prozessende. Weder ein produktives Persistenz-Backend
noch eine Cross-Process-Durability-Garantie ist implementiert.

Die gespeicherte Graph-Repräsentation enthält nur serializer-sichere Primitive und
LangChain-Messages. Der Agent stellt projektspezifische Result Types erst an seiner
öffentlichen Grenze wieder her und vermeidet damit Checkpoint-Deserialisierung eigener
Python-Objekte.

Die Approval-Pflicht ist deterministisch: Read Tools unterbrechen nie,
`create_maintenance_ticket` benötigt immer Approval. Das LLM kann eine Action
vorschlagen, aber nicht entscheiden, ob Approval nötig ist. Resume akzeptiert nur
`approve` oder `reject`. Ein ungültiger Resume wird abgelehnt, bevor die Action läuft.

LangGraph kann einen unterbrochenen Node beim Resume von Anfang an erneut starten.
Deshalb ist Code vor `interrupt()` side-effect-free und die nicht idempotente Operation
liegt in einem separaten Node nach Approval. Der In-Memory-Ticket-Adapter verwendet
zusätzlich die Tool-Call-ID als Idempotenzschlüssel, sodass eine wiederholte Ausführung
nach Approval kein zweites Ticket anlegt.

Der Checkpoint behält den bereits ausgewählten Profile-Namen und die explizite
Classification. Ein Resume routet nicht erneut, ändert keine Classification und führt
keinen Cloud-Fallback ein. Derselbe finale `EgressCheckedLLMClient` bleibt die
Model-Grenze.

## Manueller Loop im Vergleich zum Graphen

Der manuelle Pfad drückt Progression durch einen Python Loop und explizite Updates der
Message-Liste aus. Der Graph-Pfad repräsentiert Progression durch typisierten State,
Nodes, Edges und eine Conditional Route. Ihre internen Message-Strukturen unterscheiden
sich, daher vergleichen Äquivalenztests beobachtbares Verhalten: Status, ausgeführte
Tools und Argumente, Tool Count und Vorhandensein der finalen Antwort.

Dieselben First-Decision- und Trajectory-Datasets laufen gegen beide Pfade. Die
Framework-Migration rechtfertigt keine Änderung ihrer Ground Truth.

## Bewusst zurückgestellt

Dieser Slice ergänzt weder ein dauerhaftes produktives Persistenz-Backend noch
Cross-Process-Ausführungsgarantien, eine Human-Approval-UI, LangSmith-Integration, MCP,
Subgraphs, Multi-Agent-Verhalten, Planner/Executor, Dynamic Tool Discovery oder
Distributed Execution.
