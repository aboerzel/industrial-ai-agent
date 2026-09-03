# ADR-003: Hexagonal Architecture

## Status

Angenommen

## Kontext

Das Projekt wird im Lauf der Zeit LLM Provider, Produktionssysteme, technische
Dokumentation, Datenbanken, MCP Server und weitere externe Technologien integrieren.
Diese Integrationen ändern sich in unterschiedlichem Tempo und dürfen weder das
industrielle Domain Model noch die Struktur des Application-Verhaltens bestimmen.

Die aktuelle Codebasis ist bewusst klein. Ihre physischen Packages sind `domain`,
`tools`, `agent` und `infrastructure`; ein separates `application`-Package existiert
noch nicht. Die Architektur benötigt deshalb verbindliche Dependency Rules, ohne
zeremonielle Layer und Interfaces zu verlangen, bevor die Codebasis genügend
Komplexität besitzt, um davon zu profitieren.

## Entscheidung

Das System folgt Hexagonal Architecture, auch Ports and Adapters genannt. Domain-Logik
und Application-Verhalten bilden den inneren Core. Externe Technologien befinden sich
außerhalb dieses Core und werden über explizite Ports und Adapter angebunden.

Dependencies zeigen grundsätzlich nach innen:

```text
External systems and provider SDKs
                |
                v
Infrastructure / Adapters
                |
                v
Application Core / Ports
                |
                v
Domain
```

Das Diagramm beschreibt die Dependency-Richtung zur Compile-Zeit, nicht die Richtung
der Aufrufe zur Laufzeit. Zur Laufzeit kann ein innerer Use Case über einen per
Dependency Injection bereitgestellten Port einen äußeren Adapter aufrufen. Domain und
Application Core dürfen niemals von `infrastructure` abhängen.

### Domain

Die Domain enthält fachliche Modelle, Value Objects, Invarianten und Domain-Regeln. Sie
darf einen Port definieren, wenn dieser vollständig in Domain-Sprache ausgedrückt ist,
wie bei `ProductHistoryRepository`.

Die Domain darf nicht abhängen von:

* LLM- oder anderen Provider-SDKs
* MCP-Implementierungen
* Datenbanken oder Persistence Frameworks
* HTTP- oder Web Frameworks
* Transport-Schemas
* anderen Infrastructure-Technologien

Domain Models repräsentieren industrielle Konzepte und Regeln. Sie dürfen nicht durch
das Schema einer externen API, eines Wire Protocol oder eines Datenbankdatensatzes
geformt werden.

### Application Core

Der Application Core enthält Use Cases und orchestriert fachliche Abläufe. Er verwendet
Domain Models und definiert die Ports für benötigte externe Fähigkeiten. Application-
Code arbeitet gegen diese Abstraktionen und nicht gegen konkrete Infrastructure-
Klassen.

Bei der aktuellen Projektgröße dürfen Application-Verantwortlichkeiten in fokussierten
`tools`- und `agent`-Modulen verbleiben. Ein expliziter `application`-Layer oder ein
`application/ports`-Package wird erst eingeführt, wenn mehrere Use Cases und Ports die
Trennung wesentlich klarer machen. Logische Dependency-Grenzen sind bereits jetzt
verbindlich; zusätzliche physische Verzeichnisse sind es nicht.

### Ports

Ports gehören auf die innere Seite der Architekturgrenze, weil der Core die benötigten
Fähigkeiten bestimmt. Aktuelle Beispiele sind `LLMClient` und
`ProductHistoryRepository`. Zukünftige Beispiele können Ports für MES, Maintenance,
Dokumentation, Image Analysis oder andere externe Services sein.

Port-Signaturen verwenden interne Modelle und Begriffe. Sie dürfen keine Typen
konkreter Provider-SDKs, Transport DTOs, Datenbankdatensätze, HTTP Request Objects oder
vergleichbare Details äußerer Layer exponieren.

### Infrastructure und Adapter

`infrastructure` enthält konkrete Implementierungen von Ports und
integrationsspezifische Konfiguration. Aktuelle Beispiele sind
`OpenAICompatibleLLMClient` und `InMemoryProductHistoryRepository`. Zukünftige Beispiele
können SQL-, MES-, MCP- oder Cloud-Adapter sein.

Infrastructure darf von Domain und Application Core abhängen, um deren Ports zu
implementieren und deren Modelle zu erzeugen. Die umgekehrte Dependency ist verboten.
Ein Adapter besitzt die Übersetzung zwischen externen Repräsentationen und internen
Modellen.

Provider-, Transport- und Persistence-spezifische DTOs verbleiben in Infrastructure.
In das System eingehende Daten werden an der Adaptergrenze übersetzt; beim Verlassen
werden interne Modelle in externe Repräsentationen übersetzt. Externe Schemas gelangen
nicht in die Domain.

### Agent und Tools

Agent-Orchestrierung darf konkrete Infrastructure-Implementierungen nicht kennen.
Agent-facing Tools und Capabilities greifen über innere Ports oder Use Cases auf
externe Systeme zu und erhalten diese Dependencies explizit.

LLM Provider Details, Modellbezeichner, Endpoints, Credentials und Provider-SDK-Typen
dürfen nicht in Agent-Logik durchsickern. ADR-002 spezialisiert diese Regel.

### Dependency Injection und Composition Root

Konkrete Adapter werden an einer Composition Root ausgewählt und verdrahtet, etwa in
einem Process Entry Point, API Bootstrap, CLI Bootstrap oder einem expliziten
Test-Setup. Domain-, Application-, `agent`- und `tools`-Module instanziieren keine
konkreten Infrastructure Dependencies versteckt und suchen sie nicht über globale
Service Locators.

Infrastructure Adapter dürfen die Erzeugung und den Lifecycle der von ihnen besessenen
externen SDK-Clients kapseln. Tests können bei Bedarf kontrollierte Client Factories
oder Adapter Fakes injizieren.

### Weiterentwicklung

Hexagonal Architecture wird durch Dependency-Richtung und Ownership der Grenzen
durchgesetzt, nicht durch eine maximale Anzahl von Packages oder Interfaces. Erzeuge
keine Layer, Ports, Adapter, Factories oder Verzeichnisse nur, damit das Repository
formal hexagonal aussieht.

Die physische Struktur wächst mit realer Komplexität. Insbesondere wird
`application/ports` aufgeschoben, bis mehrere Use Cases oder Ports es nützlich machen.
Ein Port wird eingeführt, wenn der Core eine externe Fähigkeit abstrahieren muss oder
mehrere Implementierungen beziehungsweise Testing Seams ihn rechtfertigen, nicht für
jede Funktion oder Klasse.

### Tests

Core-Logik muss ohne reale externe Systeme testbar sein. Ports müssen in Unit Tests
durch Fakes oder Stubs ersetzbar sein. Unit Tests benötigen keine live LLMs,
Datenbanken, MES-Systeme, MCP Server oder Cloud Services.

Integration Tests prüfen konkrete Adapter separat und müssen explizit erkennbar sein.
Manuelle Smoke Tests dürfen eine konfigurierte lokale oder entfernte Integration
prüfen, sind aber kein Teil deterministischer Unit Tests.

### Beziehung zu früheren Entscheidungen

ADR-001 etablierte die anfänglichen Package-Bereiche und das Prinzip inkrementeller
Architektur. Dieses ADR ergänzt die verbindlichen Dependency Rules für diese Bereiche.

ADR-002 ist eine konkrete Anwendung dieser übergeordneten Entscheidung: `LLMClient` ist
ein innerer Port mit provider-unabhängigen Modellen, während
`OpenAICompatibleLLMClient` ein Infrastructure Adapter ist. Provider-Konfiguration,
SDK Objects und Response-Übersetzung verbleiben außerhalb des Core. Semantische Model
Profiles verhindern, dass Provider- und Modelldetails in Agent- und Use-Case-Code
durchsickern.

## Alternativen

### Nur nach technischen Layern ohne Dependency Inversion organisieren

Verworfen, weil das Benennen von Verzeichnissen als `domain`, `service` und
`infrastructure` nicht verhindert, dass innerer Code konkrete Datenbanken, SDKs oder
HTTP Clients importiert. Die Dependency Rules bilden die Architekturentscheidung.

### Externe Systeme direkt in Use Cases integrieren

Verworfen, weil Use Cases dadurch an Provider-Lifecycles, Schemas und Testumgebungen
gekoppelt würden. Der Austausch einer Integration würde Änderungen an der fachlichen
Orchestrierung erfordern.

### Sofort eine vollständige `application/ports/adapters`-Hierarchie erzeugen

Für den aktuellen Stand verworfen, weil dies vor allem leere Struktur und Indirektion
hinzufügen würde. Die logischen Grenzen passen bereits zur kleinen Codebasis und können
physisch expliziter werden, wenn die Anzahl der Use Cases und Ports dies rechtfertigt.

### Domain Models durch externe Schemas bestimmen lassen

Verworfen, weil Änderungen an Providern und Transporten dadurch industrielle Konzepte
und Invarianten destabilisieren würden. Adapter müssen diese Änderungen durch
explizites Mapping auffangen.

## Konsequenzen

Positiv:

* fachliche Regeln und Application-Verhalten bleiben unabhängig von
  Integrationstechnologien
* externe Provider und Persistence-Mechanismen können hinter stabilen Ports
  ausgetauscht werden
* Core Tests bleiben deterministisch und schnell
* Änderungen externer Schemas bleiben an Adaptergrenzen gekapselt
* die Architektur kann inkrementell wachsen, ohne verbindliche Grenzen aufzugeben

Negativ:

* Adaptergrenzen benötigen expliziten Übersetzungscode
* die Dependency-Richtung muss bei Änderungen an Imports oder Objekterzeugung geprüft
  werden
* einige Abstraktionen gehören dem Core, obwohl ihre erste Implementierung in
  Infrastructure liegt
* die Package-Struktur kann sich später mit wachsender Application-Komplexität ändern
