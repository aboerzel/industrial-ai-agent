# MCP-Grundlagen

## Zweck

Der erste MCP-Slice exponiert die bestehenden schreibgeschuetzten Factory-Capabilities
ueber einen lokalen `factory_mcp`-Server. Der LangGraph Read-Only-Pfad verwendet diesen
Server nun ueber einen echten Protokoll-Client; der manuelle direkte Pfad bleibt eine
fachliche Referenz.

## Rollen

Ein **MCP Host** ist die Anwendung, die eine oder mehrere MCP-Client-Verbindungen
verwaltet. Ein **MCP Client** baut eine Verbindung zu einem Server auf, initialisiert das
Protokoll und verwendet die vom Server angebotenen Features. Ein **MCP Server**
veroeffentlicht interoperable Capabilities. Das Projekt besitzt derzeit einen kleinen
Client des offiziellen SDKs und einen lokalen Server. Der LangGraph MCP-Pfad ist nun ein
MCP Host fuer eine Factory-Verbindung pro Agent Run; es gibt noch keinen
Multi-Server-Multiplexer.

## Tools, Resources und Prompts

MCP **Tools** sind aufrufbare Operationen mit entdeckbaren Input Schemas. `factory_mcp`
bietet aktuell genau `get_product_history(product_id)` und
`get_machine_status(station_id)` an. Ihre Structured Results erhalten Identifier,
Found/Not-Found-Status, Zeitstempel, Maschinenzustaende und Error Codes.

MCP **Resources** sind adressierbare Kontextdaten, die ein Server anbieten kann. MCP
**Prompts** sind vom Server bereitgestellte Prompt Templates. Sie sind in diesem Slice
nur Protokollkonzepte: Weder Resources noch Prompts werden implementiert.

## Discovery, Transport und Docker

Der Client initialisiert zuerst eine MCP Session und listet die Tools, die der Server
tatsaechlich anbietet. Er dupliziert keinen statischen Tool-Katalog. `factory_mcp`
unterstuetzt dieselben Tool-Definitionen und dieselbe Protokoll-Semantik ueber zwei
Transports des offiziellen SDK v2:

* **stdio** ist prozessgekoppelt: Der Client startet den lokalen Server als Child Process
  und kommuniziert ueber Standard Input und Output. Es bleibt fuer Entwicklung und
  deterministische Tests nuetzlich, weil weder Listener noch Port-Konfiguration noetig
  sind.
* **Streamable HTTP** ist vernetzt: Der Server besitzt einen Listener und exponiert
  `/mcp`; ein Client verbindet sich mit seiner konfigurierten URL. Es ist der
  Deployment-Pfad fuer `factory_mcp`.

Die Composition Root des Servers waehlt `stdio` oder `streamable-http`; Capabilities,
Handler, Domain und Agent-Orchestrierung enthalten keine Transport-Conditionals. Der
HTTP Client verwendet die offizielle API `streamable_http_client(url)` zusammen mit
derselben `ClientSession` wie stdio. Fuer einen einzelnen Agent Run initialisiert er
einmal, entdeckt einmal, fuehrt alle sequenziellen Calls in dieser Session aus und
schliesst sie danach. Dieser Slice verwendet bewusst weder eine Session pro Tool Call
noch einen Connection Pool.

Docker paketiert den vernetzten Server als reproduzierbaren Non-Root-Python-3.12-Service.
Die lokale `compose.yaml` mappt Host-Port `8001` auf den Container; Source Mount, `.env`,
Secret, Hugging-Face-Model oder Ollama-Model sind nicht erforderlich. Docker ist nicht
MCP: Docker startet und isoliert einen Process, MCP definiert dagegen Discovery, Schemas,
Messages und Tool-Call-Semantik. Docker ist hier sinnvoll, weil die Zielarchitektur
mehrere eigenstaendig deploybare MCP Services enthalten wird. Internes Docker Networking,
Agent Container, TLS und Reverse Proxy bleiben bewusst zurueckgestellt.

## LangGraph Tool Execution

Fuer einen asynchronen LangGraph MCP Run oeffnet der Adapter die ausgewaehlte stdio- oder
HTTP-Session, ruft
`initialize()` auf, entdeckt Tools, filtert sie ueber die explizite
Read-Only-Autorisierungsmenge und erstellt LangChain-`StructuredTool`-Objekte. Der Graph
erwartet jeden Tool-Aufruf sequenziell ueber `ainvoke()` und schliesst die Session nach
seinem finalen Result. Es gibt kein `asyncio.run()` in einer Graph Node oder einem Tool
Handler; die CLI besitzt den Top-Level Event Loop.

Das kleine Modul `mcp_langchain_tool_provider.py` ist ein **TEMPORARY COMPATIBILITY
ADAPTER**. Es uebersetzt nur MCP Name, Description, Input Schema, Invocation und
Structured Result. Es muss geprueft und entfernt werden, sobald stabiles
`langchain-mcp-adapters` MCP SDK v2 unterstuetzt.

MCP Discovery und Agent Authorization sind getrennt: Discovery beobachtet alles, was der
Server anbietet, waehrend der Troubleshooting Agent nur seine zwei autorisierten
Read-Only-Factory-Tools erhaelt. Das bestehende `create_maintenance_ticket`-HITL bleibt
auf dem direkten Pfad und ist kein MCP Tool.

## Security Boundary

MCP ist keine Model-Egress-Grenze. Die Model Node des Graphen verwendet das ausgewaehlte
Profile weiterhin durch `EgressCheckedLLMClient`; ADR-009 blockiert weiterhin
vertraulichen oder eingeschraenkten Kontext fuer Public-Cloud-Model Profiles. Eine lokale
HTTP-Verbindung zum Factory Container ist MCP Service-Network-Transport, keine
Autorisierung, Factory Results an `public_fast` zu senden. Der lokale Factory MCP Server
autorisiert keine Model Calls und keinen Cloud Egress. Aktuelle Tool Results erhalten in
diesem Slice keinen neuen Classification Contract; bestehende Classification-Semantik
bleibt unveraendert.

Die erste Docker-Demo hat bewusst keine MCP Authentication, weil sie fuer Entwicklung
einen lokalen Host-Port bindet. Das ist kein Security Model fuer Remote Deployment.
Authentication und Transport Security sind erforderliche Design-Arbeit vor jeder
Remote- oder Production-Exponierung.

## OBSOLETE CANDIDATES AFTER MCP MIGRATION

Diese Eintraege noch nicht entfernen. Nachdem der HTTP/Docker-MCP-Pfad alle vorgesehenen
direkten LangGraph Consumers ersetzt hat, muss der spaetere Cleanup Slice Folgendes
pruefen:

* die Read-Only-Closure-Implementierungen in
  `LangGraphTroubleshootingAgent._create_direct_tools()`;
* den direkten Read-Only-Zweig von `LangGraphTroubleshootingAgent._tool_node()`;
* direkte Konstruktion von `ProductHistoryCapability` und `MachineStatusCapability` in
  reinen LangGraph-Composition-Roots.
* stdio-only Helper Construction in produktionsorientierten LangGraph-Composition-Roots,
  sobald diese Roots explizite Transport-Konfiguration verwenden; stdio selbst bleibt ein
  unterstuetzter Entwicklungs- und Testtransport.

Die Capabilities selbst, `factory_mcp`, der manuelle Agent und die Approval Action sind
keine Obsolete Candidates.

## MCP und andere Konzepte

MCP ist kein LangChain Tool. Ein MCP Server exponiert Tools auf Protokollebene; ein
LangChain Adapter kann entdeckte Tools spaeter in LangChain Contracts uebersetzen. Das
aktuelle stabile Release von `langchain-mcp-adapters` bleibt mit MCP SDK v2 inkompatibel.
Eine Aenderung fuer v2-Support ist in Arbeit, aber noch kein stabiles Release; das Projekt
behaelt seine eine schmale Bridge bei, bis sich das aendert.

MCP ist nicht REST. REST exponiert ueblicherweise Application Resources ueber HTTP
Paths, waehrend MCP AI-orientierte Capability Discovery, Tool Schemas und mehrere
Transports standardisiert. Beide koennen nebeneinander bestehen, wenn ein System sie
braucht.

MCP ist kein Agent. Es waehlt keine Tools aus, bewertet keine Results, routet keine
Modelle und erzwingt keinen Model Egress. Bestehende Capabilities behalten ihre
Semantik; ADR-008 und ADR-009 bleiben fuer Model Routing und Security zustaendig, wenn
spaeter eine Agent Integration eingefuehrt wird.
