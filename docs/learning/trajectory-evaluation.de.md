# Troubleshooting-Trajectory-Evaluation

## Zweck und Abgrenzung

Die Trajectory-Evaluation misst vollständige reale Runs des begrenzten LangGraph-MCP-
Agenten. Sie ergänzt die bestehende First-Decision-Evaluation, ersetzt
sie aber nicht:

* Die First-Decision-Evaluation fragt, ob das Modell initial das erwartete Tool mit den
  erwarteten Argumenten ausgewählt hat. Sie führt keine Tools aus.
* Die Trajectory-Evaluation fragt, ob der Agent die vollständige erwartete Tool-Sequenz
  durchlaufen und mit dem erwarteten Status terminiert hat.

Dataset-Laden und -Validierung, deterministisches Scoring, reale Agent-Ausführung und
JSON-Reporting bleiben getrennte Funktionen. Es wird kein allgemeines Eval-Framework
eingeführt.

## Dataset

`evals/datasets/troubleshooting_trajectory_v1.jsonl` wird mit dem Repository
versioniert. Jeder unabhängige Fall enthält:

* eine stabile `case_id`;
* den natürlichsprachigen `user_input`;
* eine geordnete `expected_trajectory` aus exakten Tool-Namen und strukturierten
  Argumenten;
* einen `expected_status` wie `SUCCESS`.

Die initialen zehn Fälle umfassen eine direkte Antwort ohne Tool, einzelne
Product-History-Abfragen, einzelne Machine-Status-Abfragen für die vorhandenen
Demo-Stationen sowie zweistufige, durch die deterministischen Demo-Daten gestützte
Product-History-zu-Machine-Status-Untersuchungen. Ein `LIMIT_REACHED`-Fall ist noch
nicht enthalten, weil die aktuellen Daten keine natürliche Troubleshooting-Aufgabe
bereitstellen, die mehr als drei erfolgreiche Calls erfordern sollte.

`AgentRunResult.executed_tool_calls` stellt die normalisierte, tatsächlich ausgeführte
Trajectory ohne providerspezifische Call-IDs oder SDK-Typen bereit. Der Report zeichnet
auch die finale Antwort auf, ihre natürlichsprachliche Qualität fließt in dieser
Version jedoch nicht ins Scoring ein.

## Metriken

Alle Metriken verwenden deterministische strukturierte Vergleiche:

* **Task Success Rate** ist der Anteil der Fälle mit sowohl exakter Trajectory als auch
  erwartetem Termination Status.
* **Exact Trajectory Accuracy** ist der Anteil der Fälle, deren tatsächliche Trajectory
  dieselbe Länge, Reihenfolge, Tool-Namen und exakt dieselben Argumentobjekte wie die
  erwartete Trajectory besitzt.
* **Tool Call Accuracy** vergleicht jeden Positions-Slot exakt. Die Anzahl der Slots pro
  Fall ist `max(expected_tool_calls, actual_tool_calls)`. Ein Slot ist nur korrekt, wenn
  beide Calls an dieser Position existieren und Tool-Name sowie Argumente exakt
  übereinstimmen. Die aggregierte Metrik lautet
  `sum(correct positional slots) / sum(all positional slots)`. Dadurch werden fehlende,
  zusätzliche, verschobene, falsch benannte und falsch parametrisierte Calls bestraft.
  Enthält ein Dataset überhaupt keine Tool-Call-Slots, ist die Metrik als `1.0`
  definiert.
* **Termination Accuracy** ist der Anteil der Fälle, deren tatsächlicher
  `AgentRunStatus` dem `expected_status` entspricht.

Jedes Ergebnis gibt außerdem `expected_tool_calls` und `actual_tool_calls` aus. Der
aggregierte Report listet Case-IDs mit fehlenden oder zusätzlichen Calls auf; jeder
fehlgeschlagene Record enthält die erwartete und tatsächliche Trajectory zur Diagnose.

Diese Metriken bewerten weder die semantische Qualität der finalen Antwort noch
Grounding, unbelegte Behauptungen, Latenz, Token-Nutzung, Kosten oder
LLM-as-a-Judge-Qualität.

## Manueller Aufruf

Starte den für das gewählte Model Profile konfigurierten Endpoint. Für das initiale
lokale `troubleshooting`-Profil muss Ollama laufen und `qwen3.5:9b` verfügbar sein.
Führe anschließend aus:

```powershell
python -m evals.run_trajectory --profile troubleshooting --mcp-transport stdio
```

Um einen lokalen JSON Report explizit zu speichern:

```powershell
python -m evals.run_trajectory `
  --profile troubleshooting `
  --mcp-transport stdio `
  --output evals/results/troubleshooting-trajectory.json
```

Generierte Dateien unter `evals/results/` werden von Git ignoriert. Dataset,
Konfiguration und Scoring-Code bleiben versioniert.

## Interpretation

Beginne mit der Task Success Rate, um zu erkennen, wie viele vollständige Runs beide
strukturellen Anforderungen erfüllt haben. Der Vergleich mit Exact Trajectory Accuracy
und Termination Accuracy trennt Routing- von Terminierungsfehlern. Tool Call Accuracy
zeigt teilweise Positionskorrektheit, während erwartete und tatsächliche Call-Anzahl
Over- und Under-Calling direkt sichtbar machen. Prüfe jede fehlgeschlagene `case_id`;
ein nicht perfekter Score ist eine zu analysierende Baseline und kein Grund, Ground
Truth oder Scoring abzuschwächen.
