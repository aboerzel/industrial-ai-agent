# MCP-Grundlagen

## Zweck

Die MCP-Slices exponieren zwei schreibgeschuetzte Capability-Bereiche: `factory_mcp` fuer
Factory-Evidenz und `knowledge_mcp` fuer Documentation Retrieval. Der LangGraph
Read-Only-Pfad verwendet beide ueber echte Protokoll-Clients; der manuelle direkte Pfad
bleibt eine fachliche Referenz.

## Rollen

Ein **MCP Host** ist die Anwendung, die eine oder mehrere MCP-Client-Verbindungen
verwaltet. Ein **MCP Client** baut eine Verbindung zu einem Server auf, initialisiert das
Protokoll und verwendet die vom Server angebotenen Features. Ein **MCP Server**
veroeffentlicht interoperable Capabilities. Das Projekt besitzt eine Client-Infrastruktur
des offiziellen SDKs und zwei lokale Server. Der LangGraph MCP-Pfad hält pro explizit
konfiguriertem Server eine Verbindung pro Agent Run; er ist kein allgemeiner
Multi-Server-Multiplexer oder Router.

## Tools, Resources und Prompts

MCP **Tools** sind aufrufbare Operationen mit entdeckbaren Input Schemas. `factory_mcp`
bietet aktuell genau `get_product_history(product_id)` und
`get_machine_status(station_id)` an. `knowledge_mcp` bietet genau
`search_documentation(query, top_k=3)` an. Sein Result erhält die normalisierte Query und
Ergebnisobjekte mit einem einsbasierten `rank`, stabiler `chunk_id`, `document_id`,
relativer `source`, Score und Provenance Metadata. Kein Framework Document oder
Vector-Store-Objekt überschreitet MCP.

MCP **Resources** sind adressierbare Kontextdaten, die ein Server anbieten kann. MCP
**Prompts** sind vom Server bereitgestellte Prompt Templates. Sie sind in diesem Slice
nur Protokollkonzepte: Weder Resources noch Prompts werden implementiert.

## Discovery, Transport und Docker

Der Client initialisiert zuerst eine MCP Session und listet die Tools, die der Server
tatsaechlich anbietet. Er dupliziert keinen statischen Tool-Katalog. Beide Server
unterstuetzen dieselben Tool-Definitionen und dieselbe Protokoll-Semantik ueber zwei
Transports des offiziellen SDK v2:

* **stdio** ist prozessgekoppelt: Der Client startet den lokalen Server als Child Process
  und kommuniziert ueber Standard Input und Output. Es bleibt fuer Entwicklung und
  deterministische Tests nuetzlich, weil weder Listener noch Port-Konfiguration noetig
  sind.
* **Streamable HTTP** ist vernetzt: Jeder Server besitzt einen Listener und exponiert
  `/mcp`; ein Client verbindet sich mit seiner konfigurierten URL. Es ist der
  Deployment-Pfad für beide Services.

Die Composition Root des Servers waehlt `stdio` oder `streamable-http`; Capabilities,
Handler, Domain und Agent-Orchestrierung enthalten keine Transport-Conditionals. Der
HTTP Client verwendet die offizielle API `streamable_http_client(url)` zusammen mit
derselben `ClientSession` wie stdio. Fuer einen einzelnen Agent Run initialisiert er
einmal, entdeckt einmal, fuehrt alle sequenziellen Calls in dieser Session aus und
schliesst sie danach. Dieser Slice verwendet bewusst weder eine Session pro Tool Call
noch einen Connection Pool.

Docker paketiert jeden vernetzten Server als reproduzierbaren Non-Root-Python-3.12-Service.
Die lokale `compose.yaml` mappt Factory-Port `8001` und Knowledge-Port `8002`. Factory
benötigt kein Modell. Knowledge enthält kein Modellartefakt, verwendet den lokalen
Host-Ollama-Endpunkt für `qwen3-embedding:0.6b` und mountet einen vorab gefüllten
benannten Hugging-Face-Cache read-only für `BAAI/bge-reranker-v2-m3`; CPU ist Default.
Lokale In-Process-Ausführung kann CUDA verwenden, während die Compose-Demo weder NVIDIA
noch einen Ollama-Container verlangt. Docker ist nicht MCP: Docker startet und isoliert
Prozesse, MCP definiert dagegen Discovery, Schemas, Messages und Tool-Call-Semantik.
Internes Docker Networking, Agent Container, TLS und Reverse Proxy bleiben zurückgestellt.

## LangGraph Tool Execution

Fuer einen asynchronen LangGraph MCP Run oeffnet der Adapter jede ausgewaehlte stdio- oder
HTTP-Session, ruft `initialize()` und Tool Discovery einmal pro Server auf, weist doppelte
Toolnamen zurück, filtert Tools über explizite Read-Only-Autorisierungsmengen und erstellt
LangChain-`StructuredTool`-Objekte. Der Graph erwartet jeden Tool-Aufruf sequenziell über
`ainvoke()` und schliesst jede Session nach seinem finalen Result. Es gibt kein
`asyncio.run()` in einer Graph Node oder einem Tool Handler; die CLI besitzt den Top-Level
Event Loop.

Das kleine Modul `mcp_langchain_tool_provider.py` ist ein **TEMPORARY COMPATIBILITY
ADAPTER**. Es uebersetzt nur MCP Name, Description, Input Schema, Invocation und
Structured Result. Es muss geprueft und entfernt werden, sobald stabiles
`langchain-mcp-adapters` MCP SDK v2 unterstuetzt.

MCP Discovery und Agent Authorization sind getrennt: Discovery beobachtet alles, was der
Server anbietet, während der Troubleshooting Agent nur seine autorisierten
Read-Only-Factory- und Knowledge-Tools erhält. Das bestehende
`create_maintenance_ticket`-HITL bleibt auf dem direkten Pfad und ist kein MCP Tool.

## Security Boundary

MCP ist keine Model-Egress-Grenze. Die Model Node des Graphen verwendet das ausgewaehlte
Profile weiterhin durch `EgressCheckedLLMClient`; ADR-009 blockiert weiterhin
vertraulichen oder eingeschraenkten Kontext fuer Public-Cloud-Model Profiles. Eine lokale
HTTP-Verbindung zu jedem Container ist MCP Service-Network-Transport, keine
Autorisierung, Factory- oder Knowledge-Results an `public_fast` zu senden. Documents,
Chunks, Queries, Embeddings und Reranker-Inputs von Knowledge MCP bleiben lokal: Ollama
ist lokal und der Cross-Encoder lädt nur aus seinem lokalen Cache. MCP autorisiert weder
Model Calls noch Cloud Egress.

Die erste Docker-Demo hat bewusst keine MCP Authentication, weil sie fuer Entwicklung
einen lokalen Host-Port bindet. Das ist kein Security Model fuer Remote Deployment.
Authentication und Transport Security sind erforderliche Design-Arbeit vor jeder
Remote- oder Production-Exponierung.

## OBSOLETE CANDIDATES AFTER MCP MIGRATION

Diese Einträge noch nicht entfernen. Die aktuelle Klassifikation ist:

* **KEEP TEMPORARILY:** direkte Factory Closures und der direkte Read-Only-Zweig; der
  direkte Pfad bleibt Referenz, solange Äquivalenz-Evidenz erhalten bleibt.
* **KEEP TEMPORARILY:** direkte Factory-Capability-Konstruktion in LangGraph
  Composition Roots; der direkte Pfad bleibt unterstützt.
* **REMOVE NOW:** direkte Knowledge Tool Closures und direkte Retriever-Injection in
  LangGraph Composition Roots; kein aktiver MCP-Pfad nutzt sie nach diesem Slice.
* **KEEP TEMPORARILY:** stdio-only Helpers; stdio ist bewusster Entwicklungs-/Test-
  Transport und kein historischer Code.
* **KEEP TEMPORARILY:** `TroubleshootingAgent`; ADR-010 behält ihn als Referenz.
* **BLOCKED BY FRAMEWORK:** `mcp_langchain_tool_provider.py`; es ist die einzelne
  temporäre MCP-SDK-v2-zu-LangChain-Bridge bis ein stabiles kompatibles Adapter-Release
  existiert.

## MCP und andere Konzepte

MCP ist kein LangChain Tool. Ein MCP Server exponiert Tools auf Protokollebene; ein
LangChain Adapter kann entdeckte Tools spaeter in LangChain Contracts uebersetzen. Das
aktuelle stabile Release von `langchain-mcp-adapters` ist `0.3.2` und besitzt weiterhin
keine veröffentlichte MCP-SDK-v2-Unterstützung. Upstream-v2-Support ist in Arbeit; das
Projekt behält seine eine schmale Bridge bis sich dies ändert.

MCP ist nicht REST. REST exponiert ueblicherweise Application Resources ueber HTTP
Paths, waehrend MCP AI-orientierte Capability Discovery, Tool Schemas und mehrere
Transports standardisiert. Beide koennen nebeneinander bestehen, wenn ein System sie
braucht.

MCP ist kein Agent. Es waehlt keine Tools aus, bewertet keine Results, routet keine
Modelle und erzwingt keinen Model Egress. Bestehende Capabilities behalten ihre
Semantik; ADR-008 und ADR-009 bleiben fuer Model Routing und Security zustaendig, wenn
spaeter eine Agent Integration eingefuehrt wird.
