# ADR-009: Datenklassifikation und Model-Egress-Policy

## Status

Akzeptiert

## Kontext

Ein Agent Model Request kann mehr als den ursprünglichen Benutzertext enthalten.
Während eines begrenzten Runs können System Instructions, Tool Results,
Produktionsdaten, abgerufene Dokumentation und weitere Observations hinzukommen. Ein
Request, der mit öffentlichen Informationen beginnt, kann daher vor einem späteren
Model Call sensitiv werden.

ADR-002 hält Provider-Details aus Agent-Code heraus, und ADR-008 definiert eine
deterministische Task-Level-Auswahl zwischen geeigneten Model Profiles. Weder die
Eignung eines Modells noch eine Prompt Instruction kann Data Egress autorisieren.
Kosten-, Qualitäts-, Verfügbarkeits- oder Fallback-Präferenzen dürfen nicht entscheiden,
ob sensitive Informationen an einen externen Provider gesendet werden dürfen.

Das Projekt benötigt eine innere, deterministische Security Boundary, die den
effektiven Modellkontext klassifiziert, ausschließlich explizit erlaubte Execution
Zones zulässt und verhindert, dass der Provider Adapter nach einer Ablehnung aufgerufen
wird. Dies ist eine projektinterne technische Klassifikation. Sie erhebt keinen
rechtlichen, vertraglichen oder regulatorischen Compliance-Anspruch.

## Entscheidung

### Deterministische Security Boundary

Datenklassifikation und Model Egress sind deterministische Verantwortlichkeiten von
Application und Policy. Ein LLM darf niemals entscheiden, ob sensitive Daten an einen
externen Provider gesendet werden dürfen.

Vor jedem Model Call muss deterministischer Code:

1. die effektive Data Classification des vollständigen ausgehenden Kontexts bestimmen,
2. die Execution Zone des ausgewählten Model Profiles lesen und validieren,
3. die explizite Egress Policy anwenden und
4. den Adapter nur aufrufen, wenn die Kombination explizit erlaubt ist.

Die Policy ist Deny-by-default. Fehlende, unbekannte, fehlerhafte oder nicht
unterstützte Klassifikationen und Execution Zones werden abgelehnt, statt einen
freizügigen Default zu erhalten.

Diese ADR legt die zukünftige Grenze und Semantik fest. Sie führt weder Enum, Policy
Service, Profile-Feld, Agent-State-Änderung, Adapter Guard noch Runtime Dependency ein.

### Initiale Datenklassifikation

Die initiale Projektklassifikation besitzt vier geordnete Stufen:

```text
PUBLIC < INTERNAL < CONFIDENTIAL < RESTRICTED
```

Ihre projektinternen technischen Bedeutungen sind:

* `PUBLIC`: für die Verarbeitung durch öffentliche Provider freigegebene Informationen,
  vorbehaltlich der verbleibenden Security- und Betriebs-Policy
* `INTERNAL`: interne Informationen, die standardmäßig nicht für die Verarbeitung durch
  öffentliche Provider freigegeben sind
* `CONFIDENTIAL`: sensitive Unternehmens- oder Kundeninformationen, die eine
  genehmigte vertrauenswürdige Verarbeitung benötigen
* `RESTRICTED`: höchste Projektschutzklasse, ausschließlich für explizit erlaubte lokale
  Verarbeitung zugelassen

Diese Bezeichnungen behaupten keine Gleichwertigkeit mit einem externen rechtlichen
oder regulatorischen Klassifikationsstandard. Änderungen ihrer Bedeutung erfordern
eine bewusste Policy-Änderung und keine LLM-Interpretation.

### Execution Zones

Model Profiles tragen konzeptionell eine validierte Execution Zone. Die initialen Zonen
sind:

* `LOCAL`: Ausführung in einer explizit konfigurierten lokalen Umgebung
* `PUBLIC_CLOUD`: Ausführung über einen externen öffentlichen Cloud Model Service

Ein lokaler Ollama Endpoint ist ein Beispiel für `LOCAL`; eine externe Model API ist
ein Beispiel für `PUBLIC_CLOUD`. Diese Beispiele legen keine Provider fest.

Provider-Name und Execution Zone sind unterschiedliche Konzepte. Ein Provider-String
beweist nicht, wo ein bestimmter Endpoint ausgeführt wird. Die Zone muss explizit
zugewiesen und validiert sein; eine fehlende oder unbekannte Zone darf niemals als
`LOCAL` interpretiert werden.

Weitere Zonen werden nur eingeführt, wenn eine reale Trust- oder Deployment-Grenze sie
erfordert.

### Initiale Egress-Matrix

Die initiale Policy erlaubt ausschließlich diese Kombinationen explizit:

| Data Classification | `LOCAL` | `PUBLIC_CLOUD` |
|---------------------|---------|----------------|
| `PUBLIC`            | Erlaubt | Erlaubt        |
| `INTERNAL`          | Erlaubt | Abgelehnt      |
| `CONFIDENTIAL`      | Erlaubt | Abgelehnt      |
| `RESTRICTED`        | Erlaubt | Abgelehnt      |

Jede nicht aufgeführte Kombination wird abgelehnt. Eine unbekannte Klassifikation,
unbekannte Zone oder ein unvollständiges Model Profile wird abgelehnt. Public-Cloud-
Modelle dürfen unter dieser initialen Policy keinen `INTERNAL`-, `CONFIDENTIAL`- oder
`RESTRICTED`-Kontext verarbeiten.

Ein `Erlaubt`-Eintrag ist notwendig, aber nicht ausreichend für einen Model Call:
Capability, Authentifizierung, Verfügbarkeit, Task Requirements und andere
deterministische Prüfungen gelten weiterhin. Diese Matrix kontrolliert ausschließlich
Model-Data-Egress.

### Klassifikations-Propagation

Die effektive Klassifikation eines Agent Runs kann strenger werden, wenn Kontext
hinzukommt. Mit der obigen Reihenfolge gilt konzeptionell:

```text
effective_classification = max(
    request_classification,
    tool_result_classifications,
    retrieval_result_classifications,
    other_added_context_classifications,
)
```

Application State muss diese Propagation später besitzen. Jede neue Observation darf
die effektive Klassifikation erhöhen, sie aber nicht stillschweigend senken. Das
Entfernen von Text aus einem Prompt beweist nicht automatisch eine sichere
Deklassifizierung; jeder zukünftige Deklassifizierungs- oder Redaction-Mechanismus
benötigt eine explizite, separat begründete Policy.

Beispiel:

```text
PUBLIC User Request
  -> get_product_history()
  -> CONFIDENTIAL Produktionsdaten
  -> effective classification = CONFIDENTIAL
  -> PUBLIC_CLOUD Profiles sind nicht mehr zulässig
```

Die verschärfte Klassifikation gilt für jeden folgenden Model Call dieses Runs. Eine
unbekannte Input-Klassifikation schlägt geschlossen fehl, statt an der Sortierung
teilzunehmen.

### Tool Results

Tool Results müssen bei Implementierung dieser Policy eine Data Classification tragen
können. Unterschiedliche Capabilities dürfen unterschiedliche Klassifikationen
erzeugen. Beispiele sind:

* öffentliche Dokumentation als `PUBLIC`
* interne Produktionsdaten als `CONFIDENTIAL`
* hochsensitive Kundendaten als `RESTRICTED`

Diese Beispiele klassifizieren nicht jedes aktuelle Demo-Tool. Konkrete Labels müssen
bei der Implementierung bewusst zugewiesen und getestet werden; diese
Dokumentationsänderung verändert keine bestehenden Tool Contracts.

### Retrieval Results

Knowledge-Retrieval-Ergebnisse müssen ebenfalls klassifizierbar werden. Source- und
Chunk-Provenance aus ADR-006 liefert Evidenz für die Anwendung Source-spezifischer
Klassifikation, ist allein aber keine Autorisierungsentscheidung.

Ein `PUBLIC` User Request macht abgerufenen Inhalt nicht öffentlich. Ergänzt Retrieval
`CONFIDENTIAL`-Inhalt, wird die effektive Klassifikation `CONFIDENTIAL`, und dieser
Inhalt darf unter der initialen Matrix nicht an ein `PUBLIC_CLOUD`-Modell gesendet
werden.

### Model Calls und Defense in Depth

Security darf nicht ausschließlich in Model-Profile-Konfiguration oder einem einzelnen
Router-Prädikat leben. Die Architektur muss zwei deterministische Kontrollen
ermöglichen:

* einen Eligibility Filter vor der ADR-008-Modellauswahl
* einen abschließenden Egress Check unmittelbar vor Aufruf des Provider Adapters

Beide Prüfungen verwenden die aktuelle effektive Klassifikation und validierte
Execution Zone. Die abschließende Prüfung schützt vor veraltetem State,
Konfigurationsfehlern, fehlerhaftem Fallback oder einem Caller, der den normalen
Routing-Pfad umgeht. Ein abgelehnter Call darf den Provider Adapter nicht erreichen.

Diese ADR verlangt keine zwei duplizierten Policy-Implementierungen. Eine
deterministische Policy kann bei Implementierung der Boundary durch explizite
Application-Verdrahtung beide Enforcement Points bedienen.

Die Regel gilt für jede zukünftige externe Modellrolle, einschließlich eines Embedding
Adapters aus ADR-007, ohne die getrennten Ports `LLMClient` und Embedding-Port zu
verschmelzen.

### Fallback und Fehler

Eine Policy-Ablehnung ist kein behebbares Signal zur Auswahl einer weniger
vertrauenswürdigen Zone. Fallback darf ausschließlich Profiles berücksichtigen, die für
die aktuelle effektive Klassifikation explizit erlaubt bleiben.

Ist kein erlaubtes Modell verfügbar, schlägt die Operation deterministisch fehl und
der externe Adapter wird nicht aufgerufen. Lokaler Ausfall, Timeout, fehlendes Profile
oder höhere Kosten dürfen für sensitive Daten keinen automatischen Fallback auf
`PUBLIC_CLOUD` auslösen.

### Logs und Traces

Observability darf die Egress Policy nicht umgehen. Prompts, Tool Results, Retrieval-
Passagen und Modellantworten behalten ihre Security-Relevanz, wenn sie in Logs oder
Traces geschrieben werden. Sensitive Inhalte dürfen nicht unkontrolliert an externe
Telemetry-Systeme gesendet werden.

Das konkrete Observability-Security-Design, Capture-Regeln auf Feldebene, Retention und
Redaction bleiben zukünftige Entscheidungen. Bis diese existieren, müssen neue Tracing-
Integrationen geschlossen fehlschlagen oder sensitive Payload-Inhalte auslassen, statt
Telemetry als vertrauenswürdig anzunehmen.

### Konfiguration und Secrets

Execution Zone und andere Security-relevante Model-Profile-Eigenschaften dürfen
konfigurierbar sein, ihr Schema und ihre Werte müssen aber deterministisch validiert
werden. Fehlende, unbekannte oder ungültige Werte werden abgelehnt. Ein öffentlicher
Endpoint darf niemals durch einen Default-Wert oder Ableitung aus dem Provider-Namen zu
`LOCAL` werden.

Cloud-Provider-Secrets verbleiben gemäß den bestehenden Regeln ausschließlich in
Environment Variables oder einem anderen genehmigten Secret-Mechanismus. Lokale nicht
authentifizierte Provider dürfen keine künstlichen benutzerseitigen Secrets benötigen.
Der Besitz eines Credentials autorisiert keinen Data Egress.

### Testing

ADR-005 gilt. Die spätere Implementierung muss mindestens folgende deterministische
Tests enthalten:

* `PUBLIC` nach `LOCAL` ist erlaubt
* `PUBLIC` nach `PUBLIC_CLOUD` ist nach der initialen Policy erlaubt
* `CONFIDENTIAL` nach `LOCAL` ist erlaubt
* `CONFIDENTIAL` nach `PUBLIC_CLOUD` ist abgelehnt
* `RESTRICTED` nach `PUBLIC_CLOUD` ist abgelehnt
* eine unbekannte Klassifikation ist abgelehnt
* eine unbekannte Execution Zone ist abgelehnt
* ein sensitiveres Tool Result erhöht die effektive Klassifikation
* Policy-Ablehnung kann keinen Cloud-Fallback auslösen
* der Adapter wird nach einer Egress-Ablehnung nicht aufgerufen

Weitere Tests müssen Konfigurationsvalidierung, monotone Propagation, Retrieval-
Klassifikation und die abschließende Pre-Adapter-Prüfung abdecken, wenn diese Slices
implementiert werden. Kein Unit Test benötigt einen echten Cloud-Aufruf.

### Hexagonal Architecture

Klassifikationssemantik, Propagation, Egress Policy und Enforcement-Entscheidungen
gehören auf die innere Application- oder Policy-Seite. Provider Adapter und provider-
spezifische DTOs verbleiben in Infrastructure. Infrastructure darf eine innere Policy-
Entscheidung weder abschwächen, umgehen noch neu interpretieren.

Die Composition Root stellt validierte Profile-Konfiguration und explizite Policy-
Dependencies bereit. Agent, Domain und Tools dürfen zur Durchsetzung von Egress keine
Provider-SDK-Typen importieren. Die genaue Package- und Port-Struktur bleibt offen, bis
die Implementierung die kleinste kohärente Form zeigt.

### Beziehung zu bestehenden Entscheidungen

ADR-002 bleibt gültig. Model Profiles verbergen weiterhin konkrete Provider- und
Modelldetails vor Agent-Code; ADR-009 ergänzt bei Implementierung explizite Execution-
Zone-Metadaten und eine Egress Boundary. Secrets verbleiben außerhalb normaler
Konfiguration.

ADR-003 regelt die Dependency-Richtung. Security Policy ist innen; konkrete Model
Adapter sind außen und dürfen ausschließlich nach einer Allow-Entscheidung aufgerufen
werden.

ADR-004 bleibt gültig. Die effektive Klassifikation wird deterministischer Application
State über den begrenzten Run, während das LLM nur für kontextuelles Urteil
verantwortlich bleibt und keinen Egress autorisieren kann.

ADR-005 regelt deterministische Policy Tests. Security-Verhalten ist eine exakte
Garantie und keine LLM-Evaluationsmetrik.

ADR-006 bleibt gültig. Retrieval Provenance unterstützt Klassifikationsevidenz, und
abgerufener Inhalt muss an der Propagation der effektiven Klassifikation teilnehmen.

ADR-007 bleibt gültig. Embeddings bleiben eine separate Modellrolle mit eigenem Port,
während dieselbe Egress Policy jeden zukünftigen externen Embedding-Aufruf beschränkt.

ADR-008 wird durch diese Entscheidung beschränkt. Security Eligibility läuft vor
Task-Level Routing, und das ausgewählte Profile wird unmittelbar vor Egress erneut
geprüft.

### Scope und Nicht-Entscheidungen

Diese ADR wählt Folgendes weder aus noch führt sie es ein:

* eine externe Data-Loss-Prevention-Plattform
* Encryption Key Management
* einen regulatorischen Klassifikationsstandard
* ein Identity and Access Management System
* eine tenant-spezifische Policy Engine
* eine externe Policy-as-Code-Plattform
* automatische Datenklassifikation durch ein LLM
* eine Redaction- oder Anonymization-Pipeline
* eine konkrete Observability-Plattform
* Produktions-Policy-Code, Enums, Profile-Felder oder Runtime Dependencies

Diese Entscheidungen bleiben offen, bis reale Anforderungen sie rechtfertigen.

## Alternativen

### 1. Security ausschließlich durch Prompt Instructions durchsetzen

Abgelehnt. Ein Prompt kann keine deterministische Garantie liefern, kann von einem
Modell ignoriert oder falsch interpretiert werden und wirkt erst, nachdem Daten die
vertrauenswürdige Grenze möglicherweise bereits verlassen haben.

### 2. Security ausschließlich in Model-Profile-Konfiguration speichern

Abgelehnt. Konfiguration beschreibt ein Profile, bestimmt aber weder die effektive
Klassifikation dynamischen Kontexts noch garantiert sie Enforcement unmittelbar vor
einem Call. Ein Routing- oder Konfigurationsfehler könnte die beabsichtigte
Einschränkung umgehen.

### 3. Das LLM Daten klassifizieren und Egress entscheiden lassen

Abgelehnt. Klassifikation und Autorisierung sind Security-Garantien und keine
probabilistischen Modellurteile. Die Entscheidung wäre anfällig für Mehrdeutigkeit,
Modellfehler und Prompt Injection.

### 4. Deterministische Data Classification und Egress Policy verwenden

Akzeptiert. Explizite geordnete Klassifikationen, validierte Execution Zones, Deny-by-
default-Regeln, monotone Propagation und Pre-Adapter-Enforcement machen die Grenze
testbar und unabhängig vom Modellverhalten.

### 5. Sofort eine Enterprise-DLP- oder Policy-Plattform einführen

Für die aktuelle Phase abgelehnt. Eine solche Plattform kann später breitere
organisatorische Anforderungen unterstützen, würde aber Integration, Policy-Sprache,
Deployment und betriebliche Komplexität ergänzen, bevor das kleine lokale Projekt sie
benötigt. Die innere Policy Boundary bleibt selbst dann notwendig, wenn später ein
externer Enforcement Adapter ergänzt wird.

## Konsequenzen

Positiv:

* Sensitive-Data-Egress wird durch deterministische, testbare Regeln gesteuert
* Security Eligibility kann nicht durch Routing-Optimierung oder Fallback überstimmt
  werden
* Klassifikation folgt Tool- und Retrieval-Observations durch einen Run
* unbekannte oder unvollständige Security-Metadaten schlagen geschlossen fehl
* abschließendes Pre-Adapter-Enforcement liefert Defense in Depth
* Provider- und Modellaustausch verändert die Klassifikationssemantik nicht

Negativ:

* zukünftige Tool-, Retrieval-, Context- und Model-Profile-Verträge benötigen
  Klassifikations- und Zone-Metadaten
* Application State muss die monotone effektive Klassifikation pflegen
* konservative Ablehnung kann die Verfügbarkeit reduzieren, wenn Klassifikations- oder
  Zone-Metadaten fehlen
* Logging- und Tracing-Integrationen benötigen eine eigene kontrollierte Egress-
  Behandlung
* spätere Deklassifizierung, Redaction, Tenant Policy oder zusätzliche Zonen benötigen
  bewusste Folgeentscheidungen
