# Architekturübersicht

## Aktuelle Architektur

Das Projekt implementiert derzeit das Abrufen der Produktionshistorie, eine
provider-unabhängige LLM-Integrationsgrenze und einen begrenzten Tool-Calling-Slice. Ein
allgemeiner Agent- oder ReAct-Loop existiert nicht.

Der implementierte Request Flow ist:

```text
User Request
    |
    v
ProductHistoryCapability.get_product_history(product_id)
    |
    v
ProductHistoryRepository
    |
    v
InMemoryProductHistoryRepository
```

Die Capability wandelt die String-Eingabe in eine `ProductId` um, lädt über die
domäneneigene Repository-Abstraktion eine `ProductHistory` und gibt ein strukturiertes
`ProductHistoryResult` zurück. Die deterministischen Demo-Daten enthalten das Produkt
`P4711`.

Verteilte Services und AI frameworks sind bewusst nicht Teil dieses Slice.

Die implementierte LLM-Grenze ist:

```text
Agent / Use Case
    |
    | semantic profile + LLMRequest
    v
LLMClient port
    |
    v
OpenAICompatibleLLMClient
    |
    | profile configuration + credentials when required
    v
Configured OpenAI-compatible endpoint
```

`config/model_profiles.toml` ordnet `troubleshooting` derzeit Ollama,
`qwen3.5:9b`, `http://localhost:11434/v1` und Temperature `0` zu. Dies ist die erste
lokale Konfiguration und keine Festlegung auf diesen Provider oder dieses Modell. Die
Profilzuordnung kann geändert werden, ohne Agent- oder Use-Case-Code anzupassen.

Der implementierte Tool-Calling-Ablauf ist:

```text
Natural-language request
    |
    v
ProductHistoryAgent
    |
    | LLMRequest + get_product_history definition
    v
LLMClient (troubleshooting profile)
    |
    +-- direct text response ----------------------------+
    |
    +-- one validated tool call                           |
            |                                             |
            v                                             |
    ProductHistoryCapability                             |
            |                                             |
            | structured tool result                      |
            v                                             |
    LLMClient final response                              |
            |                                             |
            +---------------------------------------------+
                                  |
                                  v
                            Final answer
```

Das LLM entscheidet, ob es das Tool anfordert, und formuliert die Antwort.
Deterministischer Python-Code erzwingt den einen bekannten Tool-Namen, validiert
`product_id`, lehnt mehr als einen Tool Call ab, dispatcht an
`ProductHistoryCapability` und serialisiert dessen strukturiertes Ergebnis. Nach einem
Tool Call werden dem finalen LLM Request keine Tools angeboten; ein weiterer
zurückgegebener Tool Call wird abgelehnt, statt einen Loop zu starten.

## Verantwortlichkeiten der Packages

### `domain`

Enthält industrielle Domänenmodelle und Regeln.

Der aktuelle Slice definiert `ProductId`, `StationId`, `ProductionStep`,
`ProductionStepStatus`, `ProductHistory` und das `ProductHistoryRepository` protocol.

Muss unabhängig bleiben von:

* LLM SDKs
* MCP
* Datenbanken
* HTTP frameworks
* anbieterspezifischer Infrastruktur

### `tools`

Enthält agent-facing capabilities.

Tools sollten aussagekräftige Domänenoperationen statt kleinteiliger Implementierungsdetails bereitstellen.

Die aktuelle Capability ist `ProductHistoryCapability.get_product_history(product_id)`.
Sie gibt ein Pydantic-`ProductHistoryResult` zurück, einschließlich eines strukturierten
Not-found-Ergebnisses.

### `agent`

Enthält provider-unabhängige LLM-Verträge und später Agenten-Orchestrierungslogik.

Die aktuelle Implementierung definiert `LLMClient`, die Auswahl über semantische
`ModelProfile`, kleine Request- und Response-Modelle sowie `ProductHistoryAgent`. Der
Agent enthält die begrenzte Orchestrierung und den festen Ein-Tool-Dispatch. Er
importiert weder das OpenAI-SDK noch benennt er einen konkreten Provider oder ein
konkretes Modell.

Spätere Verantwortlichkeiten können Folgendes umfassen:

* tool selection
* agent loop
* state
* context construction
* routing
* execution limits

### `infrastructure`

Enthält technische Integrationen und externe Implementierungen.

Die aktuellen Implementierungen sind `InMemoryProductHistoryRepository`, das einen
kleinen deterministischen Demo-Datensatz bereitstellt, und
`OpenAICompatibleLLMClient`, das den provider-unabhängigen LLM-Vertrag in eine
OpenAI-compatible Chat Completions API übersetzt.

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

## Weiterentwicklung

Die Architektur sollte nur dann weiterentwickelt werden, wenn implementierte Fähigkeiten dies erfordern.

Mögliche spätere Stufen sind:

```text
Agent Runtime
    |
    +-- State
    +-- Context Builder
    +-- Policy Layer
    |
    v
Tool Router
    |
    v
MCP Multiplexer
    |
    +-- Factory MCP
    +-- Production MCP
    +-- Knowledge MCP
    +-- Vision MCP
```

Dies ist eine Zielrichtung und nicht die aktuelle Implementierung.

Model Profiles wie `vision`, `planning` oder `evaluation` können über Konfiguration
ergänzt werden, sobald ihre Capabilities implementiert werden. Ein nicht
OpenAI-kompatibler Provider benötigt einen weiteren Infrastructure Adapter hinter
demselben `LLMClient`-Port; ein spekulativer Multi-Provider Router existiert heute
nicht. Die Entscheidung und ihre Trade-offs beschreibt
[ADR-002](../decisions/ADR-002-provider-and-model-independent-llm-architecture.de.md).
