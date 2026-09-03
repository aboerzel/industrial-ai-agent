# Architekturübersicht

## Aktuelle Architektur

Das Projekt enthält derzeit nur die strukturelle Grundlage.

Die vorgesehene anfängliche Architektur ist:

```text
User Request
    |
    v
Agent
    |
    v
Domain Tool
    |
    v
Deterministic Domain / Infrastructure Code
```

Die ersten Implementierungsschritte werden bewusst auf verteilte Services und AI frameworks verzichten.

## Verantwortlichkeiten der Packages

### `domain`

Enthält industrielle Domänenmodelle und Regeln.

Muss unabhängig bleiben von:

* LLM SDKs
* MCP
* Datenbanken
* HTTP frameworks
* anbieterspezifischer Infrastruktur

### `tools`

Enthält agent-facing capabilities.

Tools sollten aussagekräftige Domänenoperationen statt kleinteiliger Implementierungsdetails bereitstellen.

### `agent`

Enthält die Agentenorchestrierungslogik.

Spätere Verantwortlichkeiten können Folgendes umfassen:

* tool selection
* agent loop
* state
* context construction
* routing
* execution limits

### `infrastructure`

Enthält technische Integrationen und externe Implementierungen.

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
