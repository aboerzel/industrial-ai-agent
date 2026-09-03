# ADR-002: Provider- und modellunabhängige LLM-Architektur

## Status

Angenommen

## Kontext

Die Agent Runtime und ihre Use Cases benötigen LLM-Beurteilungen, ohne die Anwendung
von einem einzelnen Modell oder Provider abhängig zu machen. Das Projekt muss lokale
Modelle für private, kostengünstige oder offline mögliche Entwicklung ebenso nutzen
können wie öffentliche Cloud-Modelle, wenn deren Qualität oder gemanagter Betrieb
hilfreich ist. Unterschiedliche Aufgaben können außerdem von unterschiedlichen
Modellen profitieren; Troubleshooting, Vision, Planning und Evaluation müssen nicht
dieselbe Modellwahl verwenden.

Provider-Namen, Modellbezeichner, Endpoints oder SDK-Typen im Agent-Code würden das
Verhalten an Infrastruktur koppeln. Dies würde auch Modellwechsel und spätere
vergleichende Evaluations unnötig aufwendig machen. Zugangsdaten dürfen nicht zusammen
mit gewöhnlichen Modelleinstellungen gespeichert oder in das Repository committed
werden.

## Entscheidung

Agent-Code und Use Cases hängen vom provider-unabhängigen `LLMClient`-Port ab. Sie
wählen ein semantisches Model Profile wie `troubleshooting`, niemals einen konkreten
Provider- oder Modellnamen. Der Port besitzt kleine Request- und Response-Modelle für
Messages, Response Text, Tool Definitions, zurückgegebene Tool Calls und Finish
Reasons. Diese Typen importieren kein Provider-SDK.

Die Zuordnung eines Profils zu Provider, Modell, Endpoint, Temperature und
Authentication Mode erfolgt über externe Konfiguration. Authentifizierte Profile geben
zusätzlich den Namen ihrer API-Key-Environment-Variable an. Ein Modell kann dadurch
ohne Änderung an Agent- oder Use-Case-Code gewechselt werden. Gewöhnliche Einstellungen
liegen in `config/model_profiles.toml`; Credential-Werte werden ausschließlich aus
Environment Variables gelesen und niemals in der Modellkonfiguration gespeichert.

Provider Adapter gehören zu `infrastructure` und übersetzen zwischen den Port-Modellen
und Provider-SDKs. Der erste und derzeit einzige Adapter unterstützt
OpenAI-compatible Chat Completions APIs. Das initiale Profil `troubleshooting` nutzt
den lokalen Ollama-Endpoint mit `qwen3.5:9b`, `http://localhost:11434/v1`, Temperature
`0` und Authentication Mode `none`. Es benötigt keine API-Key-Environment-Variable.
Falls das OpenAI-SDK technisch ein nicht leeres `api_key`-Argument verlangt, stellt der
Infrastructure Adapter intern einen nicht geheimen Platzhalter bereit. Dieser
Platzhalter ist weder ein Credential noch Modellkonfiguration und für den `LLMClient`-
Port unsichtbar. Dieses initiale Setup ist eine Konfigurationswahl und keine
architektonische Festlegung auf Ollama oder dieses Modell.

Weitere Profile wie `vision`, `planning` oder `evaluation` können ergänzt werden,
sobald eine reale Capability sie benötigt. Vergleichende Evaluations können später
dieselben Fälle mit unterschiedlichen Profilzuordnungen ausführen und Qualität,
Latenz, Token-Nutzung und Kosten aufzeichnen, ohne den evaluierten Use Case zu ändern.

Diese Entscheidung ist eine konkrete Anwendung der übergeordneten Hexagonal
Architecture aus [ADR-003](ADR-003-hexagonal-architecture.de.md): `LLMClient` ist ein
innerer Port, provider-unabhängige Request- und Response-Typen gehören zur Core-Grenze
und `OpenAICompatibleLLMClient` ist ein äußerer Infrastructure Adapter. Provider-SDK-
Objekte werden an dieser Adaptergrenze übersetzt und gelangen nicht in Agent- oder
Use-Case-Code.

Wenn ein benötigter Provider nicht OpenAI-compatible ist, kann ein eigener
Infrastructure Adapter denselben `LLMClient`-Port implementieren. Aktuell werden weder
Provider Registry noch generischer Multi-Provider Router, Fallback Chain oder andere
spekulative Abstraktionen eingeführt. Ein solches Routing kommt erst hinzu, wenn ein
zweiter inkompatibler Provider einen konkreten Bedarf erzeugt.

## Alternativen

### Provider-SDKs direkt aus Agent-Code referenzieren

Verworfen, weil dadurch SDK-Typen, Zugangsdaten, Endpoints und konkrete
Modellbezeichner in Orchestrierung und Use Cases gelangen würden. Modellwechsel und
deterministische Unit Tests würden schwieriger.

### Konkrete Modellnamen in Use Cases verwenden

Verworfen, weil die Aufgabenabsicht stabiler als die Modellverfügbarkeit ist.
Semantische Profile halten Use Cases verständlich und erlauben Modellwechsel allein
durch Konfiguration.

### Ollama und `qwen3.5:9b` dauerhaft standardisieren

Verworfen, weil lokale und Cloud-Modelle unterschiedliche betriebliche und qualitative
Trade-offs haben. Das initiale lokale Profil ist für die Entwicklung nützlich, aber
keine dauerhafte Plattformentscheidung.

### Jetzt ein vollständiges Multi-Provider-Routing-Framework bauen

Verworfen, weil derzeit nur ein Protocol Adapter benötigt wird. Eine generische
Provider Registry oder ein Fallback Framework würde Annahmen festschreiben, die noch
nicht an einem realen zweiten Provider überprüft wurden.

## Konsequenzen

Positiv:

* Agent- und Use-Case-Code bleibt unabhängig von Provider-SDKs und Modellbezeichnern
* lokale und Cloud-Endpoints können über Konfiguration gewählt werden
* aufgabenspezifische Modelle und spätere vergleichende Modell-Evaluations werden
  unterstützt
* Secrets bleiben außerhalb der committed Modellkonfiguration
* provider-spezifische Übersetzung ist isoliert und ohne Live-API-Aufrufe testbar

Negativ:

* das Projekt besitzt einen kleinen Satz eigener LLM-Request- und Response-Modelle
* bis zur Implementierung eines weiteren Adapters ist nur das OpenAI-compatible
  Protocol nutzbar
* Konfigurationsfehler und fehlende Environment Variables für authentifizierte Profile
  müssen zur Laufzeit klar fehlschlagen
* einige provider-spezifische Fähigkeiten können bewusste spätere Erweiterungen des
  Ports erfordern
