# ADR-001: Projektgrundlage

## Status

Angenommen

## Kontext

Das Projekt soll anhand eines industriellen Fehlerbehebungsszenarios praktische Fähigkeiten im Bereich Agentic / Applied AI Engineering aufbauen.

Ein wesentliches Risiko besteht darin, zu viele Frameworks und Abstraktionen einzuführen, bevor die zugrunde liegenden Mechanismen verstanden sind.

Das Repository sollte daher eine schrittweise Entwicklung von deterministischem Python-Code hin zu zunehmend agentischen und verteilten Fähigkeiten unterstützen.

## Entscheidung

Verwende Python 3.12+ mit einem `src` package layout.

Teile den Code in die folgenden Architekturbereiche auf:

* `domain`
* `tools`
* `agent`
* `infrastructure`

Verwende:

* Pydantic für strukturierte Systemgrenzen
* pytest für Tests
* Ruff für Linting und Formatierung

Führe in der anfänglichen Projektphase kein agent framework, MCP framework, keine vector database und keine distributed architecture ein.

Wichtige Architekturentscheidungen werden als ADRs dokumentiert.

## Alternativen

### Direkt mit LangGraph oder einem anderen agent framework beginnen

Für die anfängliche Phase verworfen, da dies wichtige Agentenmechanismen verbergen und Abstraktion hinzufügen würde, bevor sie erforderlich ist.

### Die vollständige MCP-Zielarchitektur sofort aufbauen

Verworfen, da dies die Infrastrukturkomplexität erhöhen würde, bevor grundlegendes Agentenverhalten und Tool-Design etabliert sind.

### Eine flache Modulstruktur verwenden

Verworfen, da sich das Projekt voraussichtlich zu einer größeren Referenzimplementierung entwickeln wird.

## Konsequenzen

Positiv:

* wichtige Mechanismen bleiben sichtbar
* die Architektur kann bewusst weiterentwickelt werden
* einfachere Tests
* gute Trennung zwischen Domäne und AI-Infrastruktur
* für Lern- und Portfoliozwecke geeignet

Negativ:

* ein Teil des Codes kann später durch Framework-Abstraktionen ersetzt werden
* die frühe Implementierung kann expliziter als unbedingt erforderlich sein
