# ADR-011: Agent-Persistenz und Human-in-the-Loop

## Status

Accepted

## Kontext

ADR-010 führte einen parallelen LangGraph-Troubleshooting-Pfad ein, stellte
Checkpointing, Persistenz, Durable Execution und Human-in-the-Loop (HITL) aber bewusst
zurück. Ein Troubleshooting Agent, der eine Write Action vorschlägt, benötigt eine
deterministische Pause, bevor die Action erfolgen kann. Er muss genug
Orchestrierungszustand erhalten, um denselben Run fortzusetzen, ohne dass LLM,
Framework-Default oder Retry Approval, Model Routing oder Model Egress umgehen können.

Dies verändert langlebiges Runtime-Verhalten und etabliert eine spätere
Persistenzgrenze. Es ist daher eine Architekturentscheidung und kein lokales
Implementierungsdetail.

## Entscheidung

### Native LangGraph-Checkpoints

Der LangGraph-Pfad verwendet LangGraphs native Checkpointer-Abstraktion. Jeder
fortsetzbare Run wird durch die native Konfigurationsform identifiziert:

```python
{
    "configurable": {
        "thread_id": "...",
    },
}
```

Dieselbe `thread_id` identifiziert die Fortsetzung eines Runs; verschiedene IDs trennen
ihre Checkpoint-Historien. Der erste Slice verwendet `InMemorySaver` ausschließlich für
deterministische Tests und lokale Demonstrationen. Er verliert allen Zustand beim
Prozessende und ist keine Entscheidung für produktive Persistenz.

Es wird keine projektspezifische parallele Thread-, Checkpoint- oder Polling-Abstraktion
eingeführt. Späterer dauerhafter Storage bleibt eine durch operative Anforderungen
begründete Infrastructure-Entscheidung.

Der gespeicherte Graph State ist auf serializer-sichere Primitive und LangChain-Message-
Verträge beschränkt. Projektspezifische Value Types werden erst an der öffentlichen
Result-Grenze des Agenten wiederhergestellt, sodass ein Checkpointer keine
projektspezifische Objekt-Deserialisierung benötigt.

### Native Interrupts und Resume

Eine Action mit erforderlicher Human Approval pausiert einen Graph Node über LangGraph
`interrupt(payload)`. Das Payload ist eine JSON-serialisierbare strukturierte Anfrage
mit stabilem `kind`, Action-Namen und nur den Details, die ein Mensch für die Entscheidung
benötigt.

Der Aufrufer setzt dieselbe `thread_id` mit `Command(resume=...)` fort. Der erste Slice
akzeptiert ausschließlich die expliziten Werte `approve` und `reject`; ungültige Werte
schlagen deterministisch fehl und führen die Action nicht aus. Der Agent implementiert
keinen eigenen Waiting Loop um Approval.

### Deterministische Approval-Grenze

Die Approval-Anforderung ist deterministische Capability Policy und keine LLM-Beurteilung:

* Die Read Capabilities `get_product_history` und `get_machine_status` laufen normal.
* Die Action Capability `create_maintenance_ticket` benötigt immer Approval.

Das LLM darf eine bekannte Action im Rahmen seiner bestehenden Tool-Auswahl vorschlagen,
aber nicht entscheiden, ob diese Action Approval braucht. Die erste Action ist nur eine
In-Memory-Demonstration; sie ruft weder ein externes Ticket-System auf noch steuert sie
Equipment.

### Side Effects und Idempotenz

LangGraph startet einen unterbrochenen Node beim Resume vom Anfang erneut. Code vor
`interrupt()` muss deshalb rein oder idempotent sein. Der Approval Node validiert und
erzeugt vor dem Interrupt nur Daten. Die Write Action wird erst in einem separaten Node
nach einem bestätigten Resume ausgeführt.

Die Demonstration Action verwendet die ID des vorgeschlagenen Tool Calls als
Idempotenzschlüssel in ihrem In-Memory-Repository. Wiederholte Ausführung des Action
Nodes liefert dasselbe Ticket zurück, statt ein zweites zu erzeugen. Dauerhafte
prozessübergreifende Idempotenzgarantien bleiben ein späteres Produktionsthema.

### Security und Model Routing

ADR-009 bleibt vor jedem Model Call bindend, auch nach einer bestätigten Action.
Checkpoints und Resumes autorisieren keinen Egress, ändern keine Data Classification und
erzeugen keinen Cloud-Fallback. Sensitiver State wird nicht unnötig in Interrupt-
Payloads oder Logs kopiert.

ADR-008 bleibt bindend. Der Composition Root wählt das semantische Model Profile vor der
Erstellung eines Runs. Das ausgewählte Profile und die Run Classification werden als
minimaler Run Context gespeichert und müssen beim Resume übereinstimmen. Ein Resume führt
niemals ein neues Routing oder Model Upgrade aus.

### Umfang

Diese ADR wählt weder produktiven Checkpointer, Persistent Store, Retention Policy,
prozessübergreifende Durability-Garantie, Web-Approval-UI, externe Ticketing-API,
PLC-Action, Background Workflow, LangSmith, MCP, Multi-Agent-Topologie, Subgraphs noch
Planner.

## Betrachtete Alternativen

### 1. Alle Runs synchron lassen und kein HITL unterstützen

Abgelehnt. Damit lässt sich weder eine sinnvolle Action-Grenze noch eine Fortsetzung
sicher demonstrieren.

### 2. Projektspezifischen Checkpoint Store und Approval-Waiting-Loop implementieren

Abgelehnt. Dies würde LangGraph-Verhalten duplizieren, eine zweite Lifecycle-Abstraktion
erzeugen und die spätere Framework-Integration schwerer nachvollziehbar machen.

### 3. Das LLM über erforderliche Approval entscheiden lassen

Abgelehnt. Approval ist deterministische Safety- und Authorization-Policy; ein LLM ist
kein vertrauenswürdiger Enforcement-Mechanismus.

### 4. Native LangGraph-Checkpoints, `interrupt()` und `Command(resume=...)` verwenden

Gewählt. Dies drückt Pause-/Resume-Semantik direkt aus und erhält gleichzeitig
projektspezifische Policy, Capabilities, Routing und Egress-Enforcement.

### 5. Sofort einen dauerhaften datenbankbasierten Checkpointer einführen

Für diesen Slice abgelehnt. Es gibt noch keine nachgewiesene operative Anforderung für
ein Produktions-Storage-Backend; eine Auswahl würde Persistenzinfrastruktur zu früh
festlegen.

## Konsequenzen

Positiv:

* der Graph kann einen einzelnen Run deterministisch pausieren und fortsetzen
* Write Actions sind von Read Tools getrennt und benötigen explizite Approval
* Action Execution kann nicht vor Approval erfolgen
* das Projekt gewinnt praktische Erfahrung mit LangGraph Checkpoints und Interrupts
* dauerhafte Persistenz kann später die In-Memory-Implementierung ersetzen, ohne die
  Approval-Semantik zu ändern

Negativ:

* Aufrufer müssen `thread_id` für eine Fortsetzung erhalten und wiederverwenden
* unterbrochene Graph Nodes benötigen sorgfältige Platzierung von Side Effects
* In-Memory-Checkpoints verschwinden beim Prozessende
* der parallele LangGraph-Pfad erhält Lifecycle-Verhalten, das der manuelle Referenzpfad
  nicht besitzt

## Beziehung zu bestehenden Entscheidungen

ADR-003 hält Persistenzadapter außerhalb des Core und verlangt explizite Composition.
ADR-004 regelt weiterhin das begrenzte sequenzielle Tool-Verhalten. ADR-005 verlangt
deterministische Tests für Approval, Rejection, Replay und Isolation. ADR-008 besitzt
die initiale deterministische Modellauswahl; ADR-009 besitzt Security Eligibility und
finalen Egress. ADR-010 besitzt die LangGraph-Orchestrierungsmigration; diese ADR
implementiert ihre bewusst zurückgestellten Checkpointing- und HITL-Grenzen nur für den
parallelen Pfad.
