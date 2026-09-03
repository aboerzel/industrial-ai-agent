# Lokale Knowledge-Retrieval-Baseline

## Zweck

Der erste Retrieval-Slice implementiert die kleinste messbare Baseline aus ADR-006. Er
durchsucht eine kleine versionierte technische Knowledge Base ohne LLM, Embeddings,
Vector Database, Reranking, MCP oder externe Retrieval Library. Retrieval bleibt vom
`TroubleshootingAgent` isoliert, damit seine Qualität unabhängig von Query-Formulierung
und Agent-Entscheidungen gemessen werden kann.

## Knowledge Base und Ingestion

Die Repository-lokale `knowledge_base/` enthält drei kompakte Markdown-Dokumente:

* `station_s04.md` beschreibt Station S04, ihre Aufgabe, den Fehlerzustand und operative
  Prüfungen.
* `error_codes.md` beschreibt E-STOP-17 und einen zweiten qualitätsbezogenen Demo-Code.
* `maintenance.md` beschreibt sicheres Vorgehen und Return-to-Service-Hinweise.

`load_markdown_chunks()` führt einen expliziten Build-Schritt aus. Die Funktion liest
die sortierten Markdown-Dateien, normalisiert Zeilenenden sowie nachgestellte
Leerzeichen und erzeugt einen Chunk pro Markdown-Überschriftsabschnitt. Anschließend
indexiert der In-Memory-Retriever diese Chunks. Runtime-Suchen verwenden den
vorbereiteten Index und lesen oder parsen die Quelldateien nicht erneut.

Für diese Baseline ist `document_id` der Dateiname ohne Endung und `source` der Pfad
relativ zum Knowledge-Base-Verzeichnis. Eine Chunk-ID besitzt die deterministische Form
`<document_id>::chunk-<dreistellige-Abschnittsposition>`, beispielsweise
`error_codes::chunk-002`. IDs bleiben stabil, solange Dokumentname und Reihenfolge der
vorherigen Überschriften unverändert bleiben. Content-Änderungen oder eingefügte
Abschnitte dürfen die Identität oder spätere Positionen verändern; content-addressed
oder manifestverwaltete IDs sind noch nicht implementiert.

## Port, Capability und Results

Der innere Port `KnowledgeRetriever` exponiert
`search(query, limit) -> tuple[KnowledgeRetrievalResult, ...]`. Die agent-facing
`DocumentationSearchCapability.search_documentation(query)` hängt ausschließlich von
diesem Port ab und fordert derzeit höchstens drei Results an.

Jedes `KnowledgeRetrievalResult` erhält:

* Passage-`content`;
* `document_id`;
* relative `source`;
* stabile `chunk_id`;
* optionalen `relevance_score`; und
* Metadata, derzeit Titel und Format des Markdown-Abschnitts.

Die Capability gibt ein strukturiertes `DocumentationSearchResult` zurück und erzeugt
keine Prosa. Dateisystemzugriff und lexical Ranking verbleiben in Infrastructure.

## Lexical Scoring

Der Baseline-Tokenizer führt Case Folding durch und extrahiert alphanumerische Terme,
wobei er Identifier mit Bindestrichen erhält. Dadurch erzeugen `E-STOP-17`,
`e-stop-17` und `E-STOP-17!!!` denselben Identifier-Token.

Für die Menge unterschiedlicher normalisierter Query-Terme `Q` und die
Chunk-Term-Menge `C` lautet der Score:

```text
score(query, chunk) = |Q intersect C| / |Q|
```

Chunks mit Score `0` werden ausgelassen. Die übrigen Chunks werden nach absteigendem
Score und anschließend zur deterministischen Tie-Auflösung nach aufsteigender
`chunk_id` sortiert. Dies ist eine transparente Term-Overlap-Baseline und kein BM25.
Sie verwendet weder Stemming, Stop-Word-Entfernung, Synonym-Erweiterung,
Phrasengewichtung, Termfrequenz-Gewichtung noch semantisches Matching.

## Retrieval-Evaluation

`evals/datasets/knowledge_retrieval_v1.jsonl` enthält zehn versionierte Fälle mit
stabilen `case_id`-Werten, natürlichen technischen Queries und exakten
`expected_relevant_chunk_ids`. Drei Fälle besitzen mehrere relevante Chunks.

Der deterministische Runner gibt Folgendes aus:

* **Hit@1:** Anteil der Fälle, deren erstes Result zu den erwarteten relevanten Chunks
  gehört.
* **Hit@k:** Anteil der Fälle mit mindestens einem erwarteten relevanten Chunk unter den
  ersten `k` Results.
* **Recall@k pro Fall:** Anzahl erwarteter relevanter Chunks, die unter den ersten `k`
  gefunden wurden, geteilt durch die Anzahl erwarteter relevanter Chunks.
* **Mean Recall@k:** arithmetischer Mittelwert der Recall@k-Werte pro Fall.

Der Report listet Hit@1-Misses, Hit@k-Misses, Fälle mit unvollständigem Recall und deren
Vereinigung als `failed_case_ids`. Jeder Fall enthält erwartete und tatsächliche
Chunk-IDs.

Die lokale Baseline wird so ausgeführt:

```powershell
python -m evals.run_retrieval
```

Ein alternatives Dataset, Knowledge-Base-Verzeichnis oder `k` kann explizit gewählt
werden:

```powershell
python -m evals.run_retrieval `
  --dataset evals/datasets/knowledge_retrieval_v1.jsonl `
  --knowledge-base knowledge_base `
  --k 3
```

Generiertes JSON kann mit `--output` unter dem von Git ignorierten Verzeichnis
`evals/results/` gespeichert werden.

## Initiales Baseline-Ergebnis

Das erste versionierte Dataset und die Implementierung liefern:

* 10 Fälle;
* Hit@1 `0.9`;
* Hit@3 `1.0`; und
* Mean Recall@3 `0.95`.

`station_quality_role` findet den erwarteten Chunk `station_s04::chunk-001` auf Rang 2
statt Rang 1. `product_failure_context_multiple` ruft
`station_s04::chunk-002` ab, verfehlt aber `error_codes::chunk-002` innerhalb der ersten
drei Results und erreicht dadurch Recall@3 `0.5`. Dataset und Ground Truth bleiben
unverändert; diese Fehler bilden die Vergleichsbaseline für spätere
Retrieval-Verbesserungen.

## Bekannte Grenzen

Der kleine Corpus und der exakte Term-Overlap-Score sind bewusst leicht
nachvollziehbar, aber nicht repräsentativ für Production Scale. Häufige Wörter können
eine nützlichere Passage überranken, Synonyme und Paraphrasen werden nicht verstanden,
alle Query-Terme besitzen dasselbe Gewicht, Abschnittspositions-IDs können sich nach
strukturellen Dokumentänderungen verschieben, und es existiert weder Index Persistence
noch Freshness Management. Grounding der finalen Antwort und Qualität der Agent Query
werden durch diese Retrieval-Baseline nicht evaluiert.
