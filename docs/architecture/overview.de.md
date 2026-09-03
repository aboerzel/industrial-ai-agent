# Architekturübersicht

## Aktuelle Architektur

Das Projekt implementiert derzeit seinen ersten deterministischen vertikalen Slice:
das Abrufen der Produktionshistorie eines Produkts.

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

Enthält die Agentenorchestrierungslogik.

Dieses Package wird vom aktuellen deterministischen Slice nicht verwendet.

Spätere Verantwortlichkeiten können Folgendes umfassen:

* tool selection
* agent loop
* state
* context construction
* routing
* execution limits

### `infrastructure`

Enthält technische Integrationen und externe Implementierungen.

Die aktuelle Implementierung ist `InMemoryProductHistoryRepository`, das einen kleinen
deterministischen Demo-Datensatz bereitstellt.

Spätere Beispiele können sein:

* LLM providers
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
