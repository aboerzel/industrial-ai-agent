# MCP-Grundlagen

## Zweck

Der erste MCP-Slice exponiert die bestehenden schreibgeschuetzten Factory-Capabilities
ueber einen lokalen `factory_mcp`-Server. Er demonstriert, wie ein echter
Protokoll-Client Tools entdeckt und aufruft, ohne ein LLM oder einen Agenten einzubeziehen.

## Rollen

Ein **MCP Host** ist die Anwendung, die eine oder mehrere MCP-Client-Verbindungen
verwaltet. Ein **MCP Client** baut eine Verbindung zu einem Server auf, initialisiert das
Protokoll und verwendet die vom Server angebotenen Features. Ein **MCP Server**
veroeffentlicht interoperable Capabilities. Das Projekt besitzt derzeit einen kleinen
Client des offiziellen SDKs und einen lokalen Server; es besitzt noch keinen Agent Host
und keinen Multi-Server-Multiplexer.

## Tools, Resources und Prompts

MCP **Tools** sind aufrufbare Operationen mit entdeckbaren Input Schemas. `factory_mcp`
bietet aktuell genau `get_product_history(product_id)` und
`get_machine_status(station_id)` an. Ihre Structured Results erhalten Identifier,
Found/Not-Found-Status, Zeitstempel, Maschinenzustaende und Error Codes.

MCP **Resources** sind adressierbare Kontextdaten, die ein Server anbieten kann. MCP
**Prompts** sind vom Server bereitgestellte Prompt Templates. Sie sind in diesem Slice
nur Protokollkonzepte: Weder Resources noch Prompts werden implementiert.

## Discovery und Transport

Der Client initialisiert zuerst eine MCP Session und listet die Tools, die der Server
tatsaechlich anbietet. Er dupliziert keinen statischen Tool-Katalog. Der lokale Smoke
verwendet stdio: Der Client startet den Server als Child Process und kommuniziert ueber
Standard Input und Output. Das ist ein kleiner lokaler Transport ohne Port. Streamable
HTTP steht im SDK zur Verfuegung, wird aber erst bei einer echten Anforderung an Remote
Deployment betrachtet.

## MCP und andere Konzepte

MCP ist kein LangChain Tool. Ein MCP Server exponiert Tools auf Protokollebene; ein
LangChain Adapter kann entdeckte Tools spaeter in LangChain Contracts uebersetzen. Das
aktuelle Release von `langchain-mcp-adapters` ist mit MCP SDK v2 inkompatibel, weil es
`mcp<2.0` verlangt. Daher wird hier kein solcher Adapter installiert.

MCP ist nicht REST. REST exponiert ueblicherweise Application Resources ueber HTTP
Paths, waehrend MCP AI-orientierte Capability Discovery, Tool Schemas und mehrere
Transports standardisiert. Beide koennen nebeneinander bestehen, wenn ein System sie
braucht.

MCP ist kein Agent. Es waehlt keine Tools aus, bewertet keine Results, routet keine
Modelle und erzwingt keinen Model Egress. Bestehende Capabilities behalten ihre
Semantik; ADR-008 und ADR-009 bleiben fuer Model Routing und Security zustaendig, wenn
spaeter eine Agent Integration eingefuehrt wird.
