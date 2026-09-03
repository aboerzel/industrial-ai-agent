# Lokale Knowledge-Retrieval-Baseline

## Zweck

Der erste Retrieval-Slice implementiert die kleinste messbare Baseline aus ADR-006; ein
zweiter Adapter ermöglicht nun einen kontrollierten rarity-aware lexical Vergleich.
Beide durchsuchen eine kleine versionierte technische Knowledge Base ohne LLM,
Embeddings, Vector Database, Reranking, MCP oder externe Retrieval Library. Retrieval
bleibt vom `TroubleshootingAgent` isoliert, damit seine Qualität unabhängig von
Query-Formulierung und Agent-Entscheidungen gemessen werden kann.

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

## Lexical Strategien

Beide Strategien verwenden denselben Tokenizer. Er führt Case Folding durch und
extrahiert alphanumerische Terme,
wobei er Identifier mit Bindestrichen erhält. Dadurch erzeugen `E-STOP-17`,
`e-stop-17` und `E-STOP-17!!!` denselben Identifier-Token.

### Einfaches Term Overlap

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

### Rarity-aware IDF Overlap

`InMemoryIdfKnowledgeRetriever` berechnet die Chunk Frequency einmalig beim Aufbau
seines Index. Für `N` indexierte Chunks und die Anzahl `df(t)` der Chunks, die Term `t`
enthalten, lautet die geglättete Inverse Document Frequency:

```text
idf(t) = ln((N + 1) / (df(t) + 1)) + 1
```

Für die Menge unterschiedlicher Query-Terme `Q` und die Chunk-Term-Menge `C` lautet der
gewichtete Score:

```text
score(query, chunk) = sum(idf(t) for t in Q intersect C)
                      / sum(idf(t) for t in Q)
```

Seltene übereinstimmende Terme tragen dadurch mehr bei als Terme, die in vielen Chunks
vorkommen. Der Score bleibt deterministisch, Chunks mit Score null werden ausgelassen
und gleiche Scores wieder nach aufsteigender `chunk_id` sortiert. Die Implementierung
ergänzt weder Stemming, Synonyme, Field Boosting, Query Expansion, Term Frequency noch
ein semantisches Signal.

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

Der Report nennt die ausgewählte Strategie und listet Hit@1-Misses, Hit@k-Misses, Fälle
mit unvollständigem Recall und deren Vereinigung als `failed_case_ids`. Jeder Fall
enthält erwartete Chunk-IDs und sein tatsächliches Ranking einschließlich Scores.

Die lokale Baseline wird so ausgeführt:

```powershell
python -m evals.run_retrieval --strategy simple
python -m evals.run_retrieval --strategy idf
```

Ein alternatives Dataset, Knowledge-Base-Verzeichnis oder `k` kann explizit gewählt
werden:

```powershell
python -m evals.run_retrieval `
  --dataset evals/datasets/knowledge_retrieval_v1.jsonl `
  --knowledge-base knowledge_base `
  --strategy idf `
  --k 3
```

Generiertes JSON kann mit `--output` unter dem von Git ignorierten Verzeichnis
`evals/results/` gespeichert werden.

## Strategievergleich

Beide Implementierungen wurden gegen das unveränderte Dataset
`knowledge_retrieval_v1.jsonl` mit zehn Fällen und dieselbe Ground Truth evaluiert:

| Metrik | Einfaches Overlap | Rarity-aware IDF |
| --- | ---: | ---: |
| Hit@1 | 0.9 | 1.0 |
| Hit@3 | 1.0 | 1.0 |
| Mean Recall@3 | 0.95 | 0.95 |
| Hit@1-Misses | `station_quality_role` | keine |
| Hit@3-Misses | keine | keine |
| Unvollständiger Recall@3 | `product_failure_context_multiple` | `product_failure_context_multiple` |

Für die zwei bekannten Problemfälle lauten die Top-3-Rankings:

| Fall und Strategie | Rang 1 | Rang 2 | Rang 3 |
| --- | --- | --- | --- |
| `station_quality_role`, einfach | `error_codes::chunk-003` (0.6250) | `station_s04::chunk-001` (0.6250) | `error_codes::chunk-001` (0.2500) |
| `station_quality_role`, IDF | `station_s04::chunk-001` (0.5504) | `error_codes::chunk-003` (0.4895) | `error_codes::chunk-001` (0.1616) |
| `product_failure_context_multiple`, einfach | `station_s04::chunk-002` (0.7000) | `maintenance::chunk-002` (0.4000) | `station_s04::chunk-003` (0.4000) |
| `product_failure_context_multiple`, IDF | `station_s04::chunk-002` (0.5923) | `maintenance::chunk-002` (0.2639) | `station_s04::chunk-003` (0.2639) |

IDF löst den Tie der einfachen Strategie für `station_quality_role`, weil der relevante
Chunk auch den selteneren Term `final` trifft. Den zweiten erwarteten Chunk für
`product_failure_context_multiple` gewinnt IDF nicht zurück: Die seltenen
produktspezifischen Query-Terme bevorzugen die Product-History-Passage deutlich, während
IDF allein kein Beziehungs- oder Phrasensignal ergänzt, das die Error-Code-Passage in
die Top 3 hebt. Kein evaluierter Fall wurde schlechter. Dataset, Ground Truth und
Scoring-Metriken wurden nach dem Vergleich nicht verändert.

## Bekannte Grenzen

Der kleine Corpus und beide Exact-Overlap-Scores sind bewusst leicht nachvollziehbar,
aber nicht repräsentativ für Production Scale. IDF modelliert ausschließlich Seltenheit
im Corpus; Synonyme, Paraphrasen, Phrasen oder Beziehungen zwischen einem Produktfehler
und seiner Error-Code-Referenz versteht es nicht. Abschnittspositions-IDs können sich
nach strukturellen Dokumentänderungen verschieben, und es existiert weder Index
Persistence noch Freshness Management. Grounding der finalen Antwort und Qualität der
Agent Query werden durch diese Retrieval-Baseline nicht evaluiert.
