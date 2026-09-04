# ADR-012: MCP-Integrationsarchitektur

**Status:** Akzeptiert

## Kontext

Das Projekt besitzt zwei etablierte, schreibgeschuetzte Application Capabilities:
`ProductHistoryCapability.get_product_history(product_id)` und
`MachineStatusCapability.get_machine_status(station_id)`. Sie werden derzeit durch
direkte In-Process-Aufrufe ausgefuehrt. Die Zielarchitektur sieht separat exponierte
Factory-, Production-, Knowledge- und Vision-Integrationen vor. Die erste
Implementierung verwendete prozessgekoppeltes stdio fuer lokale Entwicklung und Tests.
Der erste eigenstaendig deploybare Service benoetigt einen Netzwerktransport und einen
schmalen Container-Lifecycle, ohne die Tool-Semantik zu aendern.

Das Model Context Protocol (MCP) ist eine langlebige Interoperabilitaets- und
Service-Grenzentscheidung. Es beeinflusst, wie Capabilities angeboten, entdeckt,
transportiert, getestet und spaeter von einem Agenten genutzt werden. Deshalb ist vor
dem ersten Server ein ADR erforderlich.

## Entscheidung

Das offizielle MCP Python SDK v2 wird als MCP-Protokollimplementierung verwendet.
Protokoll, Discovery, Schemas oder Transports werden nicht selbst implementiert.

Jeder MCP-Server ist ein Infrastructure-Adapter ueber einen begrenzten, fachlich
kohärenten Capability-Bereich. Die ersten beiden Server sind `factory_mcp` und
`knowledge_mcp`. `factory_mcp` exponiert genau diese schreibgeschuetzten Tools:

* `get_product_history(product_id)` fuer historische Produktionsinformationen.
* `get_machine_status(station_id)` fuer den aktuellen Zustand einer Station.

`knowledge_mcp` exponiert genau `search_documentation(query, top_k=3)`. Es delegiert an
die bestehende Documentation-Search-Capability und ihren `KnowledgeRetriever`-Port; der
MCP-Handler besitzt weder Ingestion, Chunking, Embeddings, Fusion noch Reranking.

Die Tool-Handler delegieren an injizierte bestehende Capabilities. Domain Models,
Repository Ports, Repositories und Capability-Semantik bleiben die Source of Truth;
keine Fachlogik und kein Repository-Zugriff werden in MCP-Handler kopiert. Tool-Antworten
verwenden die Structured-Content-Unterstuetzung von MCP und erhalten die Semantik der
Capability-Ergebnisse, einschliesslich IDs, Found/Not-Found-Status, Zeitstempeln,
Zustaenden und Error Codes.

Clients muessen Tools ueber das Protokoll vom MCP-Server entdecken. Sie duerfen keinen
separaten statischen Tool-Katalog pflegen. Ein kleiner Client des offiziellen SDKs zeigt
Initialisierung, Tool Listing und Aufrufe.

Jeder MCP-Server unterstuetzt zwei Transports des offiziellen SDK v2 ueber dieselbe
Serverinstanz und dieselben Tool-Definitionen:

* stdio bleibt fuer prozessgekoppelte lokale Entwicklung und deterministische Tests
  erhalten.
* Streamable HTTP ist der Deployment-Transport. Der Server laeuft an extern
  konfiguriertem Host und Port und exponiert den vom SDK verwalteten Endpunkt `/mcp`.

Die Transportauswahl gehoert ausschliesslich zu einer Server- oder Client-Composition
Root. Capabilities, Tool Handler, Domain Models, Agent-Orchestrierung und Tool Contracts
verzweigen nicht nach Transport. Ein HTTP Client oeffnet pro Agent Run eine
zustandsbehaftete Streamable-HTTP-Session, initialisiert sie, entdeckt Tools einmal,
fuehrt die sequenziellen Calls aus und schliesst sie nach dem Run. Er erzeugt weder eine
Session pro Tool Call noch einen Connection Pool.

Die ersten deploybaren Varianten sind schlanke Python-3.12-Docker-Images, die nur die
Runtime Dependencies ihres Servers enthalten, als Non-Root User laufen und Streamable
HTTP standardmaessig starten. Die lokale Compose-Demo mappt je einen Host-Port auf die
Services. Docker ist ein Deployment- und Process-Isolation-Mechanismus, kein Bestandteil
von MCP und kein Ersatz fuer dessen Protokoll-Semantik. Internes Docker Networking,
Reverse Proxy, TLS und ein Agent Container bleiben zukuenftige Arbeit.

`langchain-mcp-adapters` darf entdeckte MCP-Tools in LangChain Tool Contracts
uebersetzen. Dieser Adapter ist nur eine Integrationskante. Bis ein stabiles
MCP-SDK-v2-kompatibles Release vorliegt, bleibt der projekteeigene Compatibility Adapter
die einzige Bridge. Sie oeffnet jeden explizit konfigurierten MCP Client einmal pro Agent
Run, entdeckt die Tools jedes Servers und exponiert LangGraph nur entdeckte, explizit
autorisierte Tools. Toolnamen muessen ueber alle konfigurierten Server eindeutig sein;
jeder doppelte Name bricht vor dem Binden eines Tools fail closed ab. Der Graph kennt
weder Docker, Host, Port, Retriever, Embedding-Modell noch Reranker.

MCP ist Transport- und Integrationstechnologie, kein Authorization-, Egress-, Routing-
oder Agent-Framework. ADR-009 bleibt die massgebliche Model-Egress-Grenze. Eine HTTP-
MCP-Verbindung zu einem lokalen Container ist Service-Network-Transport, keine Erlaubnis,
Tool-Daten an ein oeffentliches Model zu senden. Die ersten Tools sind schreibgeschuetzt
und bauen keine Public-Cloud-Verbindung auf. Authentication fehlt bewusst nur fuer die
lokale Docker-Demo; jedes Remote- oder Production-Deployment benoetigt vor einer
Exponierung ein explizites Authentication- und Transport-Security-Design.

## Abhaengigkeitsgrenzen

```text
Domain Repository Ports und Models
        ^
Application Capabilities
        ^
factory_mcp / knowledge_mcp Infrastructure Server Adapter
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
* Jeder Server bleibt ein Infrastructure-Adapter ueber einer begrenzten Menge bestehender
  Capabilities. Explizit konfigurierte Multi-Server-Discovery wird unterstuetzt;
  allgemeines Routing, Multiplexing und dynamische Serverauswahl bleiben inkrementelle
  Entscheidungen.
* Server- und Client-Lifecycle, Protokollkompatibilitaet, Schemas, Structured Results
  und stdio-zu-HTTP-Transportaequivalenz erhalten fokussierte deterministische
  Integrationstests.
* Docker Build und Container Smoke bleiben explizite lokale Deployment Checks und sind
  keine Voraussetzung fuer die normale Unit-Test-Suite.
* Die LangGraph-Integration verwendet denselben entdeckten MCP Tool Path ueber einen
  injizierten Provider; sie konstruiert keinen Container und umgeht keine Egress Control.
* Allgemeines Multi-Server-Routing, MCP-Authentication ausserhalb der lokalen Demo,
  Remote-Production-Deployment, Write Tools, Resources, Prompts und MCP-basiertes HITL
  bleiben ausserhalb des Scopes.
* Eine spaetere Agent-Integration muss vor jedem Model Call weiterhin ADR-008-Routing
  und den finalen Egress Check aus ADR-009 anwenden; MCP schwaecht diese Kontrollen nicht.
