# ADR-012: MCP-Integrationsarchitektur

**Status:** Akzeptiert

## Kontext

Das Projekt besitzt zwei etablierte, schreibgeschuetzte Application Capabilities:
`ProductHistoryCapability.get_product_history(product_id)` und
`MachineStatusCapability.get_machine_status(station_id)`. Sie werden derzeit durch
direkte In-Process-Aufrufe ausgefuehrt. Die Zielarchitektur sieht separat exponierte
Factory-, Production-, Knowledge- und Vision-Integrationen vor, aber bislang wurde
keine Transportgrenze ausgewaehlt oder implementiert.

Das Model Context Protocol (MCP) ist eine langlebige Interoperabilitaets- und
Service-Grenzentscheidung. Es beeinflusst, wie Capabilities angeboten, entdeckt,
transportiert, getestet und spaeter von einem Agenten genutzt werden. Deshalb ist vor
dem ersten Server ein ADR erforderlich.

## Entscheidung

Das offizielle MCP Python SDK v2 wird als MCP-Protokollimplementierung verwendet.
Protokoll, Discovery, Schemas oder Transports werden nicht selbst implementiert.

Der erste `factory_mcp`-Server ist ein Infrastructure-Adapter. Er exponiert genau diese
schreibgeschuetzten Tools:

* `get_product_history(product_id)` fuer historische Produktionsinformationen.
* `get_machine_status(station_id)` fuer den aktuellen Zustand einer Station.

Die Tool-Handler delegieren an injizierte bestehende Capabilities. Domain Models,
Repository Ports, Repositories und Capability-Semantik bleiben die Source of Truth;
keine Fachlogik und kein Repository-Zugriff werden in MCP-Handler kopiert. Tool-Antworten
verwenden die Structured-Content-Unterstuetzung von MCP und erhalten die Semantik der
Capability-Ergebnisse, einschliesslich IDs, Found/Not-Found-Status, Zeitstempeln,
Zustaenden und Error Codes.

Clients muessen Tools ueber das Protokoll vom MCP-Server entdecken. Sie duerfen keinen
separaten statischen Tool-Katalog pflegen. Ein kleiner Client des offiziellen SDKs zeigt
Initialisierung, Tool Listing und Aufrufe. Tests verwenden, sofern verfuegbar, den
In-Process- oder In-Memory-Testpfad des SDKs. Der manuelle lokale Smoke verwendet stdio,
weil dafuer kein Listener-Port, Reverse Proxy oder Deployment-Konfiguration erforderlich
ist. Streamable HTTP bleibt eine spaetere Deployment-Entscheidung und wird hier nicht
festgelegt.

`langchain-mcp-adapters` darf entdeckte MCP-Tools in LangChain Tool Contracts
uebersetzen. Dieser Adapter ist nur eine Integrationskante. Dieser Slice verbindet
MCP-Tools weder mit LangGraph noch mit einem LLM oder Agenten.

MCP ist Transport- und Integrationstechnologie, kein Authorization-, Egress-, Routing-
oder Agent-Framework. ADR-009 bleibt die massgebliche Model-Egress-Grenze. Die ersten
Tools sind schreibgeschuetzt und bauen keine Public-Cloud-Verbindung auf.

## Abhaengigkeitsgrenzen

```text
Domain Repository Ports und Models
        ^
Application Capabilities
        ^
factory_mcp Infrastructure Server Adapter
        ^
MCP Clients / LangChain MCP Adapter
```

Konkrete Repositories und Capabilities werden in einer expliziten Composition Root
erstellt und in den MCP-Server injiziert. MCP-SDK- und LangChain-MCP-Typen duerfen nicht
in Domain, Repository Ports oder Capability Result Types gelangen.

## Betrachtete Alternativen

### 1. Ausschliesslich direkte In-Process-Calls behalten

Dies ist der einfachste aktuelle Pfad, bietet jedoch keine Protokoll-Discovery und keine
interoperable Service-Grenze fuer spaetere Clients.

### 2. Ein eigenes JSON-RPC- oder HTTP-Protokoll implementieren

Das wuerde ausgereifte Protokoll-, Schema-, Discovery- und Transportverantwortlichkeiten
duplizieren und die Interoperabilitaet verringern. Es wird abgelehnt.

### 3. Zuerst REST Endpoints exponieren

REST ist fuer Application APIs moeglich, aber MCP modelliert direkt entdeckbare AI Tool
Contracts und hat kompatible Clients. REST wuerde fuer diesen Use Case einen zweiten
Integrationsvertrag hinzufuegen.

### 4. Das offizielle MCP SDK v2 mit einem kleinen Server-Adapter einfuehren

Gewahlt. Es bietet standardisierte Tools, Discovery, Structured Content und unterstuetzte
lokale Transports, ohne die bestehenden Application Capabilities zu veraendern.

### 5. LangGraph oder LangChain Server und Tool-Semantik ueberlassen

Abgelehnt. Framework Tool Objects ersetzen die Capability-Grenze nicht und wuerden die
MCP-Verfuegbarkeit von einer bestimmten Agent Runtime abhaengig machen.

## Konsequenzen

* MCP wird der Standard fuer den externen Tool-Transport bewusst exponierter
  Projekt-Capabilities.
* Jeder kuenftige Server bleibt ein Infrastructure-Adapter ueber einer begrenzten Menge
  bestehender Capabilities; Service-Topologie und Deployment bleiben inkrementelle
  Entscheidungen.
* Server- und Client-Lifecycle, Protokollkompatibilitaet und Tool-Schemas erhalten
  fokussierte deterministische Integrationstests.
* LangGraph-Integration, Multi-Server-Routing, Knowledge MCP, MCP-Authentifizierung,
  Remote Deployment, Write Tools, Resources, Prompts und MCP-basiertes HITL werden durch
  dieses ADR weder entschieden noch implementiert.
* Eine spaetere Agent-Integration muss vor jedem Model Call weiterhin ADR-008-Routing
  und den finalen Egress Check aus ADR-009 anwenden; MCP schwaecht diese Kontrollen nicht.
