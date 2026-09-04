# Baseline für die Tool-Selection-Evaluation

## Zweck

Die Baseline misst die erste LLM-Entscheidung des LangGraph-MCP-Pfads anhand des
versionierten Datasets
`evals/datasets/troubleshooting_tool_selection_v1.jsonl`. Jeder Fall wird mit einem
frischen Message Context ausgewertet und enthält eine stabile `case_id`, einen
natürlichsprachigen `user_input`, ein `expected_tool` und exakte
`expected_arguments`.

Das initiale Dataset enthält zwölf ausgewogene Fälle: sechs für `get_product_history`
und sechs für `get_machine_status`. Es umfasst englische und deutsche Formulierungen
sowie in jedem Fall einen eigenen Produkt- oder Stations-Identifier.

## Metriken

Der Runner gibt zwei deterministische Exact-Match-Metriken aus:

* **Tool Selection Accuracy** ist der Anteil der Fälle mit genau einem Tool Call, dessen
  Name mit `expected_tool` übereinstimmt.
* **Argument Accuracy** ist der Anteil aller Fälle mit genau einem Call, dem korrekten
  Tool und einem Argumentobjekt, das exakt `expected_arguments` entspricht.

Argument Accuracy ist bewusst strenger: Eine Response mit dem falschen Tool kann keinen
Punkt für die Argumente erhalten. Ein fehlender oder mehrfacher Tool Call gilt für
beide Metriken als falsch. Die strukturierte Ausgabe pro Fall enthält erwartetes und
tatsächliches Tool, Argumente, Anzahl der Tool Calls, beide Bewertungen und mögliche
Ausführungsfehler.

Diese Baseline bewertet weder Tool-Ausführung, Tool Results, Qualität der finalen
Antwort, Grounding, Latenz, Token-Nutzung, Kosten noch LLM-as-a-Judge-Qualität.

## Manueller Aufruf

Starte den für das ausgewählte Model Profile konfigurierten Endpoint. Für das initiale
lokale `troubleshooting`-Profil muss Ollama laufen und `qwen3.5:9b` verfügbar sein.
Führe anschließend aus:

```powershell
python -m evals.run_tool_selection --profile troubleshooting --mcp-transport stdio
```

Der Report wird als JSON auf Standard Output geschrieben. Um ein lokales Ergebnis
explizit zu speichern:

```powershell
python -m evals.run_tool_selection `
  --profile troubleshooting `
  --mcp-transport stdio `
  --output evals/results/troubleshooting.json
```

Dateien unter `evals/results/` werden von Git ignoriert, damit generierte Läufe nicht
versehentlich versioniert werden. Dataset und Model-Profile-Zuordnung bleiben
versioniert. Prüfe ein Ergebnis bewusst, bevor du es mit Force-Add als kuratiertes
Baseline-Artefakt aufnimmst.

## Interpretation

Eine Accuracy von `1.0` bedeutet, dass alle zwölf Fälle für die jeweilige Metrik exakt
übereinstimmen. Prüfe bei einem niedrigeren Wert die einzelnen Case Records:
Selection-Fehler weisen auf Routing-Probleme hin, während ein korrektes Tool mit
`arguments_correct=false` Fehler bei der Extraktion isoliert. Temperature `0` reduziert
Varianz, macht aber nicht jedes LLM Backend vollkommen deterministisch; wiederholte
Läufe können daher zur Bewertung der Stabilität sinnvoll sein.
