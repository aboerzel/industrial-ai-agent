# Lokale Knowledge-Retrieval-Baseline

## Zweck

Der Retrieval-Slice implementiert zwei messbare lexikalische Baselines aus ADR-006:
einfaches Term Overlap und rarity-aware IDF Overlap. Version 2 erweitert Corpus und
Evaluation Set vor jeder BM25-Implementierung, damit ein späterer Strategievergleich
nicht seinen eigenen Benchmark beeinflussen kann. Beide bestehenden Retriever bleiben
unverändert und laufen ohne LLM, Embeddings, Vector Database, Reranking, MCP, Query
Rewriting oder externe Retrieval Library. Retrieval bleibt vom
`TroubleshootingAgent` isoliert.

## Knowledge Base und Ingestion

Die Repository-lokale `knowledge_base/` enthält sieben kompakte Markdown-Dokumente:

* `station_s04.md` beschreibt Station S04, ihre Aufgabe, den Fehlerzustand und operative
  Prüfungen.
* `error_codes.md` beschreibt E-STOP-17 und einen zweiten qualitätsbezogenen Demo-Code.
* `maintenance.md` beschreibt sicheres Vorgehen und Return-to-Service-Hinweise.
* `station_s02.md` beschreibt Press-Fit Assembly, POS-31, AX-Y2-Diagnose und Recovery.
* `vision_calibration.md` behandelt CAM-12, CAL-42, Calibration und Verifikation.
* `production_quality.md` behandelt Inspection Evidence, Lot-Korrelation und Disposition.
* `troubleshooting_service.md` behandelt wiederkehrende Fehler und Service-Evidence-Pakete.

`load_markdown_chunks()` liest die sortierten Markdown-Dateien, normalisiert
Zeilenenden sowie nachgestellte Leerzeichen und erzeugt einen Chunk pro
Markdown-Überschriftsabschnitt. Der In-Memory-Retriever indexiert diese Chunks einmalig;
Runtime-Suchen lesen die Quelldateien nicht erneut. Die Erweiterung vergrößert den
Corpus von 9 auf 25 Chunks.

Für diese Baseline ist `document_id` der Dateiname ohne Endung und `source` der Pfad
relativ zum Knowledge-Base-Verzeichnis. Eine Chunk-ID besitzt die deterministische Form
`<document_id>::chunk-<dreistellige-Abschnittsposition>`, beispielsweise
`error_codes::chunk-002`. IDs bleiben stabil, solange Dokumentname und Reihenfolge der
vorherigen Überschriften unverändert bleiben.

## Port, Capability und Results

Der innere Port `KnowledgeRetriever` exponiert
`search(query, limit) -> tuple[KnowledgeRetrievalResult, ...]`. Die agent-facing
`DocumentationSearchCapability.search_documentation(query)` hängt ausschließlich von
diesem Port ab und fordert derzeit höchstens drei Results an.

Jedes `KnowledgeRetrievalResult` erhält Passage Content, `document_id`, relative
`source`, stabile `chunk_id`, optionalen `relevance_score` und Metadata. Die Capability
gibt ein strukturiertes Result zurück und erzeugt keine Prosa. Dateisystemzugriff und
lexical Ranking verbleiben in Infrastructure.

## Lexikalische Strategien

Beide unveränderten Strategien verwenden denselben Tokenizer. Er führt Case Folding
durch und extrahiert alphanumerische Terme, wobei er Identifier mit Bindestrichen
erhält. Dadurch erzeugen `E-STOP-17`, `e-stop-17` und `E-STOP-17!!!` denselben Token.

### Einfaches Term Overlap

Für die Menge unterschiedlicher normalisierter Query-Terme `Q` und die
Chunk-Term-Menge `C` lautet der Score:

```text
score(query, chunk) = |Q intersect C| / |Q|
```

Chunks mit Score `0` werden ausgelassen. Die übrigen Chunks werden nach absteigendem
Score und anschließend nach aufsteigender `chunk_id` sortiert. Es gibt weder Stemming,
Stop-Word-Entfernung, Synonym-Erweiterung, Phrasengewichtung,
Termfrequenz-Gewichtung noch semantisches Matching.

### Rarity-aware IDF Overlap

Für `N` indexierte Chunks und die Anzahl `df(t)` der Chunks, die Term `t` enthalten,
lautet die geglättete Inverse Document Frequency:

```text
idf(t) = ln((N + 1) / (df(t) + 1)) + 1
```

Für die Menge unterschiedlicher Query-Terme `Q` und die Chunk-Term-Menge `C` lautet der
gewichtete Score:

```text
score(query, chunk) = sum(idf(t) for t in Q intersect C)
                      / sum(idf(t) for t in Q)
```

Die Implementierung ergänzt weder Stemming, Synonyme, Field Boosting, Query Expansion,
Term Frequency noch ein semantisches Signal.

## Retrieval-Evaluation-Datasets

`evals/datasets/knowledge_retrieval_v1.jsonl` bleibt mit seinen zehn ursprünglichen
Fällen byte-identisch. `knowledge_retrieval_v2.jsonl` enthält 28 Fälle: die zehn
v1-Fälle mit unveränderter `case_id`, Query und Relevance Ground Truth sowie 18 neue
Fälle. Neun v2-Fälle besitzen mehrere relevante Chunks.

Jeder v2-Fall trägt eine oder mehrere beschreibende Kategorien. Kategorien überlappen,
weil eine realistische Query gleichzeitig einen exakten Identifier enthalten, kurz
sein und mehrere Dokumente benötigen kann.

| Kategorie | Fälle |
| --- | ---: |
| Exakte Identifier | 15 |
| Natural Language | 17 |
| Seltene Terme | 7 |
| Common-Term-Ambiguität | 14 |
| Multi-Relevance | 9 |
| Kurze Queries | 5 |
| Längere technische Queries | 5 |
| Dokumentübergreifende Ambiguität | 20 |
| Termfrequenz-sensitive Fälle | 4 |
| Längensensitive Fälle | 6 |

Die Ground Truth wurde durch Lesen der Source Chunks und die fachliche Bestimmung der
Passagen erstellt, die jede Query beantworten. Alle antworttragenden Chunks wurden
aufgenommen; Fälle mit unklarer Relevanz wurden ausgeschlossen. Retriever-Rankings
wurden weder zum Erstellen noch zum Überarbeiten der Labels verwendet. Der
deterministische Loader weist leere Felder, doppelte Case IDs, doppelte Queries,
doppelte relevante Chunk IDs, doppelte Kategorien und Schema-Verletzungen zurück. Ein
separater Validierungsschritt weist doppelte Corpus-Chunk-IDs und jede nicht in der
geladenen Knowledge Base existierende Ground-Truth-Referenz zurück. Er prüft keine
Retrieval-Qualität.

Der Runner gibt Hit@1, Hit@3, Recall@3 pro Fall und Mean Recall@3 aus. Er listet
Hit@1-Misses, Hit@3-Misses, Fälle mit unvollständigem Recall und deren Vereinigung als
`failed_case_ids`. Jeder Fall enthält erwartete Chunk IDs und sein tatsächliches
Ranking einschließlich Scores. Für v2 werden dieselben Metriken und Fehlerlisten mit
direkter Runner-Logik auch nach Kategorie aggregiert.

Die eingefrorene v2-Baseline wird so ausgeführt:

```powershell
python -m evals.run_retrieval --dataset evals/datasets/knowledge_retrieval_v2.jsonl --strategy simple
python -m evals.run_retrieval --dataset evals/datasets/knowledge_retrieval_v2.jsonl --strategy idf
```

Das ursprüngliche v1-Dataset bleibt mit `--dataset
evals/datasets/knowledge_retrieval_v1.jsonl` auswählbar. Generiertes JSON kann mit
`--output` unter dem von Git ignorierten Verzeichnis `evals/results/` gespeichert
werden.

## Freeze-Regel

Der Corpus mit sieben Dokumenten und die v2 Ground Truth wurden am 04.09.2026 vor dem
ersten v2-Retrieval-Lauf eingefroren. Der SHA-256-Wert des Datasets beim Freeze lautet
`E535816185D90DA816C5FD2033865094BD430E3752AE19632647E82309A46EA6`.
Weder v2-Queries noch Relevance Labels dürfen aufgrund späterer BM25-Ergebnisse
verändert werden. Auch Corpus-Wortlaut und Chunking für diesen Vergleich sind
eingefroren. Eine notwendige Korrektur muss explizit als spätere Dataset-Version
erfolgen, statt v2 stillschweigend umzuschreiben.

## v1- und v2-Baselines

Die v1-Werte sind die historische Baseline mit drei Dokumenten vor der
Corpus-Erweiterung. Die v2-Werte verwenden den eingefrorenen Corpus mit sieben
Dokumenten und 25 Chunks.

| Dataset | Metrik | Einfaches Overlap | Rarity-aware IDF |
| --- | --- | ---: | ---: |
| v1 (10 Fälle) | Hit@1 | 0.9000 | 1.0000 |
| v1 (10 Fälle) | Hit@3 | 1.0000 | 1.0000 |
| v1 (10 Fälle) | Mean Recall@3 | 0.9500 | 0.9500 |
| v2 (28 Fälle) | Hit@1 | 0.7857 | 0.8571 |
| v2 (28 Fälle) | Hit@3 | 0.8929 | 0.9286 |
| v2 (28 Fälle) | Mean Recall@3 | 0.8155 | 0.8452 |

Ein optionaler v1-Regression-Lauf gegen den erweiterten Corpus mit 25 Chunks
reproduzierte für beide Strategien dieselben v1-Metriken und Fehlerlisten.

Die v2-Fehlerlisten sind:

| Fehler | Einfaches Overlap | Rarity-aware IDF |
| --- | --- | --- |
| Hit@1-Misses | `station_quality_role`, `positioning_causes_natural`, `s02_recovery_verification`, `calibration_invalid_after_work`, `calibration_procedure`, `qv1_role_short` | `positioning_causes_natural`, `s02_recovery_verification`, `calibration_procedure`, `qv1_role_short` |
| Hit@3-Misses | `s02_recovery_verification`, `calibration_procedure`, `qv1_role_short` | `s02_recovery_verification`, `calibration_procedure` |
| Unvollständiger Recall@3 | `product_failure_context_multiple`, `positioning_causes_natural`, `s02_recovery_verification`, `calibration_procedure`, `qv1_role_short`, `service_evidence_multiple`, `vision_recovery_multiple` | `product_failure_context_multiple`, `positioning_causes_natural`, `axis_encoder_short`, `s02_recovery_verification`, `calibration_procedure`, `service_evidence_multiple`, `vision_recovery_multiple` |

## v2-Ergebnisse nach Kategorie

| Kategorie (n) | Einfach H@1 | Einfach H@3 | Einfach MR@3 | IDF H@1 | IDF H@3 | IDF MR@3 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Exakte Identifier (15) | 0.8667 | 0.8667 | 0.7889 | 0.8667 | 0.9333 | 0.8444 |
| Natural Language (17) | 0.7059 | 0.8824 | 0.8235 | 0.8235 | 0.8824 | 0.8235 |
| Seltene Terme (7) | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.9286 |
| Common-Term-Ambiguität (14) | 0.7143 | 0.7857 | 0.7857 | 0.7857 | 0.8571 | 0.8571 |
| Multi-Relevance (9) | 0.8889 | 1.0000 | 0.7593 | 0.8889 | 1.0000 | 0.7407 |
| Kurze Queries (5) | 0.8000 | 0.8000 | 0.8000 | 0.8000 | 1.0000 | 0.9000 |
| Längere technische Queries (5) | 1.0000 | 1.0000 | 0.6667 | 1.0000 | 1.0000 | 0.7333 |
| Dokumentübergreifende Ambiguität (20) | 0.7500 | 0.9000 | 0.7917 | 0.8500 | 0.9500 | 0.8333 |
| Termfrequenz-sensitiv (4) | 0.5000 | 0.7500 | 0.6250 | 0.5000 | 0.7500 | 0.6250 |
| Längensensitiv (6) | 0.8333 | 1.0000 | 0.7222 | 0.8333 | 1.0000 | 0.7778 |

## Bekannte Fehlermuster

Beide Strategien verfehlen Paraphrasen und morphologische Varianten, weil ihnen
Stemming und ein semantisches Signal fehlen. Das zeigt sich bei
`s02_recovery_verification` und `calibration_procedure`. Häufiges Vokabular und die
deterministische Tie-Auflösung über Chunk IDs können die beabsichtigte Passage
überholen, insbesondere bei kurzen Queries wie `qv1_role_short`. Multi-Relevance-Fälle
finden häufig einen korrekten Chunk, verlieren aber eine ergänzende Passage an einen
teilweise passenden Konkurrenten; IDF verbessert die aggregierten v2-Werte, reduziert
aber Mean Recall@3 der Multi-Relevance-Kategorie leicht. Beide Strategien reduzieren
Chunks auf Term-Mengen, sodass wiederholte zentrale Terme kein Termfrequenz-Signal
liefern. Keiner der Scores normalisiert nach Chunk-Länge.

Diese gemessenen Lücken machen BM25 zu einem sinnvollen nächsten Vergleich: Es kann
Termfrequenz-Sättigung und Längennormalisierung ergänzen, ohne die etablierte
lexikalische Grenze zu verändern. Der Vergleich muss den eingefrorenen v2-Corpus und
die Ground Truth unverändert verwenden.

## Bekannte Grenzen

Der Corpus bleibt bewusst klein und manuell nachvollziehbar, statt Production Scale
abzubilden. Abschnittspositions-IDs können sich nach strukturellen Dokumentänderungen
verschieben, und es existiert weder Index Persistence noch Freshness Management.
Grounding der finalen Antwort und Qualität der Agent Query werden durch diese
Retrieval-Baseline nicht evaluiert.
