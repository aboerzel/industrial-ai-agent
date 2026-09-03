# Architekturübersicht

## Aktuelle Architektur

Das Projekt implementiert derzeit das Abrufen der Produktionshistorie und des aktuellen
Maschinenstatus, eine provider-unabhängige LLM-Integrationsgrenze und einen begrenzten
Slice zur Auswahl zwischen zwei Tools. Eine kleine deterministische Baseline evaluiert
die erste LLM-Tool-Entscheidung. Ein allgemeiner Agent, ReAct-Loop oder ein
Eval-Framework existiert nicht.

Der implementierte Request Flow ist:

```mermaid
flowchart LR
    subgraph Core["Application Core"]
        PHC["ProductHistoryCapability"]
        MSC["MachineStatusCapability"]
    end

    subgraph Ports["Domain-eigene Ports"]
        PHR["ProductHistoryRepository"]
        MSR["MachineStatusRepository"]
    end

    subgraph Infrastructure["Infrastructure Adapter"]
        PHM["InMemoryProductHistoryRepository"]
        MSM["InMemoryMachineStatusRepository"]
    end

    PHC -->|"ProductId"| PHR
    MSC -->|"StationId"| MSR
    PHM -.->|"implementiert"| PHR
    MSM -.->|"implementiert"| MSR

    classDef core fill:#e8f1ff,stroke:#2563eb,color:#172554
    classDef port fill:#f5f3ff,stroke:#7c3aed,color:#2e1065
    classDef adapter fill:#ecfdf5,stroke:#059669,color:#022c22
    class PHC,MSC core
    class PHR,MSR port
    class PHM,MSM adapter
```

Jede Capability wandelt ihren String-Identifier in das passende Domain Value Object um,
lädt über eine domäneneigene Repository-Abstraktion und gibt ein strukturiertes Ergebnis
zurück. Die deterministischen Demo-Daten enthalten das Produkt `P4711` und die Stationen
`S04` und `S12`.

Verteilte Services und AI frameworks sind bewusst nicht Teil dieses Slice.

Die implementierte LLM-Grenze ist:

```mermaid
flowchart LR
    A["Agent / Use Case"] -->|"semantisches ModelProfile + LLMRequest"| P["LLMClient port"]
    C["OpenAICompatibleLLMClient"] -.->|"implementiert"| P
    TOML["config/model_profiles.toml<br/>Provider, Modell, Base URL, Temperature, Auth-Modus"] --> C
    ENV["Environment Variables<br/>API Keys nur für authentifizierte Profile"] -.-> C
    C -->|"providerspezifischer Request"| E["Konfigurierter OpenAI-compatible Endpoint"]

    subgraph Core["Application Core"]
        A
        P
    end

    subgraph Infrastructure["Infrastructure"]
        C
        TOML
        ENV
    end

    subgraph External["Externes System"]
        E
    end

    classDef core fill:#e8f1ff,stroke:#2563eb,color:#172554
    classDef adapter fill:#ecfdf5,stroke:#059669,color:#022c22
    classDef external fill:#fff7ed,stroke:#ea580c,color:#431407
    class A,P core
    class C,TOML,ENV adapter
    class E external
```

`config/model_profiles.toml` ordnet `troubleshooting` derzeit Ollama,
`qwen3.5:9b`, `http://localhost:11434/v1` und Temperature `0` zu. Dies ist die erste
lokale Konfiguration und keine Festlegung auf diesen Provider oder dieses Modell. Die
Profilzuordnung kann geändert werden, ohne Agent- oder Use-Case-Code anzupassen.

Der implementierte Tool-Calling-Ablauf ist:

```mermaid
sequenceDiagram
    actor User
    participant Agent as TroubleshootingAgent
    participant LLM as LLMClient<br/>(troubleshooting profile)
    participant Product as ProductHistoryCapability
    participant Machine as MachineStatusCapability

    User->>Agent: Natürlichsprachige Anfrage
    Agent->>LLM: LLMRequest + genau zwei Tool-Definitionen

    alt Direkte Antwort
        LLM-->>Agent: Antworttext ohne Tool Call
    else Ein Tool Call
        LLM-->>Agent: LLMToolCall
        Note over Agent: Anzahl, Tool-Name und toolspezifische<br/>Argumente deterministisch validieren
        alt get_product_history
            Agent->>Product: get_product_history(product_id)
            Product-->>Agent: ProductHistoryResult
        else get_machine_status
            Agent->>Machine: get_machine_status(station_id)
            Machine-->>Agent: MachineStatusResult
        end
        Agent->>LLM: Strukturiertes Tool Result, keine Tools angeboten
        LLM-->>Agent: Finaler Antworttext
    end

    Agent-->>User: Finale Antwort
```

Das LLM entscheidet, ob es `get_product_history` oder `get_machine_status` anfordert
oder direkt antwortet, und formuliert die finale Antwort. Deterministischer Python-Code
validiert den ausgewählten Namen gegen diese zwei bekannten Tools, validiert die
toolspezifische `product_id` oder `station_id`, lehnt mehr als einen Tool Call ab,
dispatcht fest an die entsprechende Capability und serialisiert deren strukturiertes
Ergebnis. Nach einem Tool Call werden dem finalen LLM Request keine Tools angeboten;
ein weiterer zurückgegebener Tool Call wird abgelehnt, statt einen Loop zu starten.

## Baseline für die Tool-Selection-Evaluation

Der Repository-lokale Eval misst ausschließlich die von
`TroubleshootingAgent.request_tool_selection()` exponierte erste Entscheidung. Jeder
versionierte JSONL-Fall startet mit einem frischen Message Context. Der Runner verwendet
ein konfigurierbares semantisches Model Profile und übergibt die provider-unabhängige
`LLMResponse` an ein deterministisches Exact-Match-Scoring.

```mermaid
flowchart LR
    D["Versioniertes JSONL-Dataset<br/>12 unabhängige Fälle"]
    R["Tool-Selection-Eval-Runner"]
    A["TroubleshootingAgent<br/>request_tool_selection()"]
    L["LLMClient<br/>konfigurierbares Model Profile"]
    S["Deterministisches Exact-Match-Scoring"]
    O["Strukturierter JSON Report<br/>Einzelergebnisse + aggregierte Metriken"]
    X["Ausgeschlossen<br/>Tool-Ausführung und finale Antwort"]

    D -->|"Fall"| R
    R -->|"user_input"| A
    A -->|"initialer LLMRequest"| L
    L -->|"erste LLMResponse"| A
    A -->|"beobachteter Tool Call"| R
    R --> S
    S --> O
    R -.->|"ruft nicht auf"| X

    classDef data fill:#fefce8,stroke:#ca8a04,color:#422006
    classDef core fill:#e8f1ff,stroke:#2563eb,color:#172554
    classDef metric fill:#ecfdf5,stroke:#059669,color:#022c22
    classDef excluded fill:#f8fafc,stroke:#64748b,color:#0f172a
    class D data
    class R,A,L core
    class S,O metric
    class X excluded
```

Tool Selection Accuracy verlangt genau einen Call mit dem erwarteten Namen. Argument
Accuracy verlangt zusätzlich die exakte Übereinstimmung der Argumente und vergibt daher
keinen Argument-Punkt für ein falsches Tool. Die Baseline bewertet weder Tool Results,
Qualität der finalen Antwort, Latenz, Kosten noch LLM-as-a-Judge-Qualität.

## Quality Strategy

[ADR-005](../decisions/ADR-005-testing-and-evaluation-strategy.de.md) trennt
Qualitätsmechanismen nach der Art der Aussage, die sie stützen. Deterministische
Garantien gehören in automatisierte Tests. Modellabhängige Urteile werden mit
versionierten Datasets, strukturierter Ground Truth und expliziten Metriken gemessen.
Smoke Tests prüfen grundlegende Live-Integration, während Traces und operative Metriken
der Observability dienen und weder Tests noch Evals ersetzen.

```mermaid
flowchart TB
    Behavior["Verhalten oder Qualitätsaussage"] --> Deterministic{"Deterministisch<br/>garantierbar?"}
    Deterministic -->|"ja"| Tests["Unit Tests<br/>schnelles Basis-Gate, Fakes/Stubs"]
    Tests --> Integration["Explizite Integration Tests<br/>konkrete Adapter"]
    Integration --> Smoke["Explizite Smoke Tests<br/>echte Services bei Bedarf"]
    Deterministic -->|"nein: Modellurteil"| Evals["Versionierte AI-/Agent-Evals<br/>strukturierte Fälle + Metriken"]
    Evals --> Current["Aktuelle Baseline<br/>Tool Selection Accuracy<br/>Tool Argument Accuracy"]
    Evals -.-> Future["Dimensionen erst mit realen Capabilities ergänzen<br/>Judge oder Human Review nur bei Bedarf"]

    classDef test fill:#e8f1ff,stroke:#2563eb,color:#172554
    classDef eval fill:#f5f3ff,stroke:#7c3aed,color:#2e1065
    classDef live fill:#fff7ed,stroke:#ea580c,color:#431407
    class Behavior,Deterministic,Tests test
    class Evals,Current,Future eval
    class Integration,Smoke live
```

Das aktuelle Repository implementiert deterministische Unit-Test-Abdeckung, explizit
dokumentierte lokale Ollama-Smoke-Pfade und den fokussierten Tool-Selection-Eval für die
erste Entscheidung. Es implementiert weder ein externes Eval-Framework noch
LLM-as-a-Judge, eine Observability-Plattform oder neue CI/CD-Infrastruktur. Generierte
Eval-Reports bleiben standardmäßig unversioniert.

## Verantwortlichkeiten der Packages

### `domain`

Enthält industrielle Domänenmodelle und Regeln.

Die aktuellen Slices definieren `ProductId`, die gemeinsam verwendete `StationId`,
`ProductionStep`, `ProductionStepStatus`, `ProductHistory`, `MachineState` und
`MachineStatus`. Die domäneneigenen Ports sind `ProductHistoryRepository` und
`MachineStatusRepository`.

Muss unabhängig bleiben von:

* LLM SDKs
* MCP
* Datenbanken
* HTTP frameworks
* anbieterspezifischer Infrastruktur

### `tools`

Enthält agent-facing capabilities.

Tools sollten aussagekräftige Domänenoperationen statt kleinteiliger Implementierungsdetails bereitstellen.

Die aktuellen Capabilities sind
`ProductHistoryCapability.get_product_history(product_id)` und
`MachineStatusCapability.get_machine_status(station_id)`. Sie geben die
Pydantic-Modelle `ProductHistoryResult` und `MachineStatusResult` zurück, jeweils
einschließlich strukturierter Not-found-Ergebnisse.

### `agent`

Enthält provider-unabhängige LLM-Verträge und später Agenten-Orchestrierungslogik.

Die aktuelle Implementierung definiert `LLMClient`, die Auswahl über semantische
`ModelProfile`, kleine Request- und Response-Modelle sowie `TroubleshootingAgent`. Der
Agent enthält die begrenzte Orchestrierung und den festen Zwei-Tool-Dispatch. Er
importiert weder das OpenAI-SDK noch benennt er einen konkreten Provider oder ein
konkretes Modell. ADR-004 akzeptiert einen begrenzten sequenziellen Tool Loop als
nächste Orchestrierungsstufe; dieser Loop ist jedoch noch nicht implementiert.

Spätere Verantwortlichkeiten können Folgendes umfassen:

* tool selection
* agent loop
* state
* context construction
* routing
* execution limits

### `infrastructure`

Enthält technische Integrationen und externe Implementierungen.

Die aktuellen Implementierungen sind `InMemoryProductHistoryRepository` und
`InMemoryMachineStatusRepository`, die kleine deterministische Demo-Datensätze
bereitstellen, sowie `OpenAICompatibleLLMClient`, das den provider-unabhängigen
LLM-Vertrag in eine OpenAI-compatible Chat Completions API übersetzt.

Normale Modelleinstellungen und Secret-Werte sind getrennt. Die Konfiguration markiert
ein Profil explizit als nicht authentifiziert oder API-Key-authentifiziert. Ein
authentifiziertes Profil speichert nur den Namen der erforderlichen Environment
Variable; sein Credential-Wert verbleibt in der Umgebung. Das initiale lokale
Ollama-Profil ist nicht authentifiziert und benötigt keinen vom Benutzer konfigurierten
API Key. Der Adapter kapselt den vom OpenAI-SDK benötigten, nicht geheimen technischen
Platzhalter.

Spätere Beispiele können sein:

* zusätzliche LLM Provider Adapter, sobald konkrete Anforderungen sie rechtfertigen
* repositories
* databases
* MCP clients
* observability
* external APIs

### `evals`

Enthält das versionierte Tool-Selection-Dataset und einen fokussierten manuellen Runner.
Parsing, Scoring pro Fall und Aggregation sind deterministisch und durch Unit Tests ohne
live LLM abgedeckt. Generierte JSON Reports gehören in das von Git ignorierte
Verzeichnis `evals/results/`, sofern sie nicht bewusst kuratiert werden.

## Weiterentwicklung

Die Architektur sollte nur dann weiterentwickelt werden, wenn implementierte Fähigkeiten dies erfordern.

### Akzeptierter nächster Schritt: Begrenzter Tool Loop

[ADR-004](../decisions/ADR-004-agent-orchestration-strategy.de.md) akzeptiert einen
expliziten, begrenzten und sequenziellen Single-Agent Tool Loop als nächste
Orchestrierungsstrategie. Dies ist eine akzeptierte Richtung und nicht die aktuelle
Implementierung: Das Produktionsverhalten erlaubt weiterhin höchstens einen Tool Call
pro Run.

```mermaid
flowchart TD
    Context["Benutzeranfrage + Observations dieses Runs"] --> LLM["LLM-Entscheidung<br/>LLMClient + semantisches Model Profile"]
    LLM --> Choice{"Finale Antwort oder ein Tool Call?"}
    Choice -->|"finale Antwort"| Done["Erfolgreich terminieren"]
    Choice -->|"ein Tool Call"| Validate["Deterministische Namens- und Argumentvalidierung"]
    Choice -->|"ungültige oder mehrere Calls"| Invalid["Mit deterministischem Fehler beenden"]
    Validate -->|"ungültig"| Invalid
    Validate -->|"gültig"| Budget{"Tool-Call-Budget verbleibt?"}
    Budget -->|"nein"| Limit["Nicht ausführen<br/>mit Limitfehler beenden"]
    Budget -->|"ja"| Execute["Deterministischer Dispatch und sequenzielle Ausführung"]
    Execute --> Observe["Strukturiertes Result als Observation anhängen"]
    Observe --> Context

    classDef llm fill:#f5f3ff,stroke:#7c3aed,color:#2e1065
    classDef deterministic fill:#e8f1ff,stroke:#2563eb,color:#172554
    classDef terminal fill:#ecfdf5,stroke:#059669,color:#022c22
    classDef failure fill:#fff1f2,stroke:#e11d48,color:#4c0519
    class LLM,Choice llm
    class Context,Validate,Budget,Execute,Observe deterministic
    class Done terminal
    class Invalid,Limit failure
```

Das Modell entscheidet, ob weitere Informationen benötigt werden. Python-Code bleibt
für Validierung, Dispatch, Ausführung, das endliche positive Tool-Call-Limit und alle
Abbruchbedingungen verantwortlich. Calls werden sequenziell mit höchstens einem Call
pro Iteration ausgeführt. Die erste Version besitzt weder parallele Ausführung,
Planner/Executor, ein Multi-Agent-System, LangGraph noch MCP als Voraussetzung. Die
bestehende Eval-Baseline für die erste Entscheidung bleibt als Regression-Vergleich
erhalten.

Mögliche spätere Stufen sind:

```mermaid
flowchart TD
    U["User / API"] --> AR["Agent Runtime"]

    subgraph Runtime["Mögliche zukünftige Runtime Capabilities"]
        AR
        State["State"]
        Context["Context Builder"]
        Policy["Policy / Guardrails"]
        Observability["Evals / Tracing"]
        AR --- State
        AR --- Context
        AR --- Policy
        AR --- Observability
    end

    AR --> Router["Tool Router"]
    Router --> Multiplexer["MCP Multiplexer"]
    Multiplexer --> Factory["Factory MCP"]
    Multiplexer --> Production["Production MCP"]
    Multiplexer --> Knowledge["Knowledge MCP"]
    Multiplexer --> Vision["Vision MCP"]

    classDef runtime fill:#e8f1ff,stroke:#2563eb,color:#172554
    classDef routing fill:#f5f3ff,stroke:#7c3aed,color:#2e1065
    classDef service fill:#fff7ed,stroke:#ea580c,color:#431407
    class AR,State,Context,Policy,Observability runtime
    class Router,Multiplexer routing
    class Factory,Production,Knowledge,Vision service
```

Dies ist eine Zielrichtung und nicht die aktuelle Implementierung.

Model Profiles wie `vision`, `planning` oder `evaluation` können über Konfiguration
ergänzt werden, sobald ihre Capabilities implementiert werden. Ein nicht
OpenAI-kompatibler Provider benötigt einen weiteren Infrastructure Adapter hinter
demselben `LLMClient`-Port; ein spekulativer Multi-Provider Router existiert heute
nicht. Die Entscheidung und ihre Trade-offs beschreibt
[ADR-002](../decisions/ADR-002-provider-and-model-independent-llm-architecture.de.md).
