# Lokale Knowledge-Retrieval-Baseline

## Zweck

Der Retrieval-Slice implementiert drei messbare lexikalische Baselines aus ADR-006:
einfaches Term Overlap, rarity-aware IDF Overlap und BM25. Er ergänzt die erste
semantische Baseline aus ADR-007 sowie eine rangfusionierte BM25-plus-semantische
Hybrid-Baseline und eine lokale Cross-Encoder-Reranking-Baseline. Version 2 erweiterte
und fror Corpus sowie Evaluation Set ein, bevor BM25, Semantic, Hybrid und Reranking
implementiert wurden. Keine dieser Strategien
konnte dadurch ihren eigenen Benchmark beeinflussen. Retrieval bleibt vom
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
alle Ranking-Implementierungen verbleiben in Infrastructure.

## Lexikalische Strategien

Alle drei Strategien verwenden denselben Tokenizer. Er führt Case Folding
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

### BM25

BM25 erhält die vollständige Document-Tokenfolge, sodass wiederholte Terme zur Term
Frequency `tf(t,d)` und zur Chunk Length `|d|` beitragen. Für Corpus-Größe `N`, Chunk
Document Frequency `df(t)` und durchschnittliche Chunk Length `avgdl` verwendet diese
Implementierung:

```text
idf_bm25(t) = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))

score(q, d) = sum(
    idf_bm25(t)
    * (tf(t,d) * (k1 + 1))
      / (tf(t,d) + k1 * (1 - b + b * |d| / avgdl))
    for each distinct t in q
)
```

`tf(t,d)` belohnt wiederholte Evidence mit abnehmendem Zusatznutzen.
`idf_bm25(t)` gibt seltenen Termen mehr Einfluss. `k1` steuert die Sättigung der Term
Frequency, während `b` die Chunk-Length-Normalisierung relativ zu `avgdl` steuert. Die
festen Baseline-Parameter sind `k1 = 1.5` und `b = 0.75`; sie wurden vor dem ersten
v2-Lauf gewählt und nicht anhand seiner Ergebnisse optimiert. Chunks mit Score null
werden ausgelassen, gleiche Scores nach aufsteigender `chunk_id` sortiert.

## Semantische Baseline

ADR-007 führt den separaten inneren Port `EmbeddingClient` mit
`embed_query(text)` und `embed_documents(texts)` ein. Er liefert ausschließlich
numerische Vektoren und exponiert keine LangChain-, Ollama- oder Provider-SDK-Typen. Der
lokale `OllamaEmbeddingClient` adaptiert LangChains `OllamaEmbeddings` mit dem
Baseline-Modell `qwen3-embedding:0.6b` unter `http://localhost:11434`.

`InMemorySemanticKnowledgeRetriever` implementiert den bestehenden
`KnowledgeRetriever`-Port. Bei der expliziten Erstellung sendet er die unveränderten 25
Chunks in einem Batch über den Embedding-Port und speichert die resultierenden Vektoren
in LangChain Cores `InMemoryVectorStore`. Zur Query-Zeit wird nur die Query embedded,
der Store nach seinen Top-k-Vector-Matches gefragt und danach über stabile `chunk_id`
auf die originalen Chunks zurückgemappt. Content und vorhandene Provenance bleiben
erhalten. Der Score ist der Similarity Score des Vector Stores und nicht numerisch mit
lexikalischen Scores vergleichbar.

Dies ist eine reine Local-Only-Baseline. Weder Dokumenttext noch Embeddings werden an
einen Cloud Provider gesendet. `numpy` ist eine direkte Dependency, weil LangChains
`InMemoryVectorStore` es für seine implementierte Similarity-Berechnung verwendet. Der
Store wird bei der expliziten Adapter-Erstellung neu gebaut; er ist weder eine
persistente Vector Database noch eine projektweite Similarity-Entscheidung.

## Hybrid-Baseline

`HybridKnowledgeRetriever` ist eine weitere Infrastructure-Implementierung des
unveränderten `KnowledgeRetriever`-Ports. Er komponiert die bestehenden BM25- und
Semantic-Retriever; Tokenizer, Index, Ranking-Algorithmus und Score der Komponenten
bleiben unverändert. Für den kleinen eingefrorenen Corpus fragt er bei beiden
Komponenten alle 25 Chunks ab und führt die Ränge anschließend mit gleichgewichteter
Reciprocal Rank Fusion (RRF) und einsbasierten Rängen zusammen:

```text
rrf_score(d) = sum(1 / (60 + rank_i(d)))
               für jedes Komponenten-Ranking i, das d enthält
```

Die Rank-Konstante ist vor dem ersten Hybrid-v2-Lauf fest auf `60` gesetzt. BM25- und
Vector-Store-Scores werden absichtlich weder addiert noch normalisiert oder sonst
verglichen, da sie inkompatible Skalen haben. Ein in beiden Rankings enthaltener Chunk
erhält beide Rangbeiträge; ein einseitiger Chunk bleibt berechtigt. Gleiche fusionierte
Scores werden deterministisch über aufsteigende `chunk_id` aufgelöst. Die installierten
Versionen von `langchain-core`, `langchain-ollama` und `langgraph` enthalten keine
stabile Ensemble-/RRF-Retriever-Komponente. Daher bleibt diese kleine deterministische
Funktion lokal, statt ein zusätzliches LangChain-Paket oder ein generisches
Fusion-Framework einzuführen.

## Reranking-Baseline

Retriever und Reranker haben unterschiedliche Aufgaben. BM25 und der semantische
Bi-Encoder liefern effizient Kandidaten; ein Cross-Encoder verarbeitet Query und eine
Kandidatenpassage gemeinsam und kann ihre direkte Relevanz genauer bewerten. Diese
gemeinsame Inferenz ist teurer und läuft daher nur auf dem kleinen Candidate Set.

Der providerneutrale innere `Reranker`-Port bietet `rerank(query, candidates)` und
liefert dieselben strukturierten Kandidaten in neuer Reihenfolge. Er exponiert keine
Torch-, Transformers-, Hugging-Face- oder Sentence-Transformers-Typen. Der lokale
`SentenceTransformersCrossEncoderReranker` adaptiert `sentence_transformers.CrossEncoder`
mit `BAAI/bge-reranker-v2-m3`. `RerankedKnowledgeRetriever` komponiert den bestehenden
Hybrid Retriever und diesen Port, validiert exakt die übergebenen Candidate IDs und
erhält Content sowie Provenance. `relevance_score` ist ein generischer Reranker-Score,
kein Framework-Typ.

Vor dem ersten rerankten v2-Lauf wurden festgelegt: BM25 Candidate Depth `10`, Semantic
Candidate Depth `10`, RRF-Konstante `60`, fusionierte Candidate Depth `10` und finale
Eval `top_k=3`. Der Reranker kann keine Chunks außerhalb dieser zehn fusionierten
Kandidaten erzeugen. Die ursprüngliche Hybrid-Baseline behält ihren Full-Corpus-Default;
nur die rerankte Komposition verwendet explizit diese Candidate Depth.

Die Inferenz ist Local-Only. Der Adapter verwendet `local_files_only=True` und lädt aus
dem lokalen Hugging-Face-Cache; Query, Chunks, Embeddings und Scores können dadurch zur
Runtime keinen Cloud-Service erreichen. Das öffentliche Modellartefakt wird vor dem
ersten lokalen Lauf explizit gecacht:

```powershell
hf download BAAI/bge-reranker-v2-m3
```

Bei erkannter CUDA verwendet der Adapter `cuda`, sonst `cpu`. Auf der verwendeten RTX
3070 lud das gecachte Modell in ungefähr 33 Sekunden; der vollständige 28-Fall-Eval
dauerte einschließlich Initialisierung ungefähr 18 Sekunden. Dies sind lokale
Beobachtungen, keine Performance-Vorgabe.

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
python -m evals.run_retrieval --dataset evals/datasets/knowledge_retrieval_v2.jsonl --strategy bm25
python -m evals.run_retrieval --dataset evals/datasets/knowledge_retrieval_v2.jsonl --strategy semantic
python -m evals.run_retrieval --dataset evals/datasets/knowledge_retrieval_v2.jsonl --strategy hybrid
python -m evals.run_retrieval --dataset evals/datasets/knowledge_retrieval_v2.jsonl --strategy reranked
python scripts/smoke_test_semantic_retrieval.py
python scripts/smoke_test_reranked_retrieval.py
```

Das ursprüngliche v1-Dataset bleibt mit `--dataset
evals/datasets/knowledge_retrieval_v1.jsonl` auswählbar. Generiertes JSON kann mit
`--output` unter dem von Git ignorierten Verzeichnis `evals/results/` gespeichert
werden.

## Freeze-Regel

Der Corpus mit sieben Dokumenten und die v2 Ground Truth wurden am 04.09.2026 vor dem
ersten v2-Retrieval-Lauf eingefroren. Der SHA-256-Wert des Datasets beim Freeze lautet
`E535816185D90DA816C5FD2033865094BD430E3752AE19632647E82309A46EA6`.
Weder v2-Queries noch Relevance Labels dürfen aufgrund späterer BM25-, Semantic-,
Hybrid- oder Reranking-Ergebnisse verändert werden. Auch Corpus-Wortlaut und Chunking für
diesen Vergleich sind eingefroren. Eine notwendige Korrektur muss explizit als spätere
Dataset-Version erfolgen, statt v2 stillschweigend umzuschreiben.

## v1- und v2-Baselines

Die v1-Werte sind die historische Baseline mit drei Dokumenten vor der
Corpus-Erweiterung. Die v2-Werte verwenden den eingefrorenen Corpus mit sieben
Dokumenten und 25 Chunks. Semantic, Hybrid und Reranking wurden auf v1 nicht gemessen.

| Dataset | Metrik | Einfaches Overlap | Rarity-aware IDF | BM25 | Semantisch |
| --- | --- | ---: | ---: | ---: | ---: |
| v1 (10 Fälle) | Hit@1 | 0.9000 | 1.0000 | 0.9000 | nicht gemessen |
| v1 (10 Fälle) | Hit@3 | 1.0000 | 1.0000 | 1.0000 | nicht gemessen |
| v1 (10 Fälle) | Mean Recall@3 | 0.9500 | 0.9500 | 0.9500 | nicht gemessen |
| v2 (28 Fälle) | Hit@1 | 0.7857 | 0.8571 | 0.7857 | 0.8571 |
| v2 (28 Fälle) | Hit@3 | 0.8929 | 0.9286 | 0.9643 | 0.9643 |
| v2 (28 Fälle) | Mean Recall@3 | 0.8155 | 0.8452 | 0.8810 | 0.8810 |

Die v1-Regression gegen den erweiterten Corpus mit 25 Chunks reproduzierte die
bestehenden Simple- und IDF-Werte. BM25 erreichte `0.9000 / 1.0000 / 0.9500`; sein
einziger Hit@1-Miss war `error_code_exact`, während
`product_failure_context_multiple` weiterhin unvollständigen Recall@3 besitzt.

Die v2-Fehlerlisten sind:

| Fehler | Einfaches Overlap | Rarity-aware IDF | BM25 |
| --- | --- | --- | --- |
| Hit@1-Misses | `station_quality_role`, `positioning_causes_natural`, `s02_recovery_verification`, `calibration_invalid_after_work`, `calibration_procedure`, `qv1_role_short` | `positioning_causes_natural`, `s02_recovery_verification`, `calibration_procedure`, `qv1_role_short` | `error_code_exact`, `positioning_causes_natural`, `s02_recovery_verification`, `calibration_procedure`, `qv1_role_short`, `service_evidence_multiple` |
| Hit@3-Misses | `s02_recovery_verification`, `calibration_procedure`, `qv1_role_short` | `s02_recovery_verification`, `calibration_procedure` | `s02_recovery_verification` |
| Unvollständiger Recall@3 | `product_failure_context_multiple`, `positioning_causes_natural`, `s02_recovery_verification`, `calibration_procedure`, `qv1_role_short`, `service_evidence_multiple`, `vision_recovery_multiple` | `product_failure_context_multiple`, `positioning_causes_natural`, `axis_encoder_short`, `s02_recovery_verification`, `calibration_procedure`, `service_evidence_multiple`, `vision_recovery_multiple` | `product_failure_context_multiple`, `positioning_causes_natural`, `axis_encoder_short`, `s02_recovery_verification`, `service_evidence_multiple`, `vision_recovery_multiple` |

## v2-Ergebnisse nach Kategorie

| Kategorie (n) | Einfach H@1/H@3/MR@3 | IDF H@1/H@3/MR@3 | BM25 H@1/H@3/MR@3 |
| --- | --- | --- | --- |
| Exakte Identifier (15) | 0.8667 / 0.8667 / 0.7889 | 0.8667 / 0.9333 / 0.8444 | 0.8000 / 1.0000 / 0.9111 |
| Natural Language (17) | 0.7059 / 0.8824 / 0.8235 | 0.8235 / 0.8824 / 0.8235 | 0.7647 / 0.9412 / 0.8824 |
| Seltene Terme (7) | 1.0000 / 1.0000 / 1.0000 | 1.0000 / 1.0000 / 0.9286 | 0.8571 / 1.0000 / 0.9286 |
| Common-Term-Ambiguität (14) | 0.7143 / 0.7857 / 0.7857 | 0.7857 / 0.8571 / 0.8571 | 0.7857 / 0.9286 / 0.9286 |
| Multi-Relevance (9) | 0.8889 / 1.0000 / 0.7593 | 0.8889 / 1.0000 / 0.7407 | 0.7778 / 1.0000 / 0.7407 |
| Kurze Queries (5) | 0.8000 / 0.8000 / 0.8000 | 0.8000 / 1.0000 / 0.9000 | 0.8000 / 1.0000 / 0.9000 |
| Längere technische Queries (5) | 1.0000 / 1.0000 / 0.6667 | 1.0000 / 1.0000 / 0.7333 | 0.8000 / 1.0000 / 0.7333 |
| Dokumentübergreifende Ambiguität (20) | 0.7500 / 0.9000 / 0.7917 | 0.8500 / 0.9500 / 0.8333 | 0.8000 / 0.9500 / 0.8333 |
| Termfrequenz-sensitiv (4) | 0.5000 / 0.7500 / 0.6250 | 0.5000 / 0.7500 / 0.6250 | 0.5000 / 1.0000 / 0.8750 |
| Längensensitiv (6) | 0.8333 / 1.0000 / 0.7222 | 0.8333 / 1.0000 / 0.7778 | 0.6667 / 1.0000 / 0.7778 |

### Semantische Fehlerlisten und Kategorien

Die semantische Baseline hat Hit@1-Misses bei `station_current_fault`,
`axis_encoder_short`, `qv1_role_short` und `vision_recovery_multiple`; ihr einziger
Hit@3-Miss ist `qv1_role_short`. Unvollständiger Recall@3 bleibt bei
`positioning_causes_natural`, `axis_encoder_short`, `positioning_long_diagnosis`,
`qv1_role_short`, `service_evidence_multiple` und `vision_recovery_multiple`.

| Kategorie (n) | Semantisch H@1/H@3/MR@3 |
| --- | --- |
| Exakte Identifier (15) | 0.7333 / 0.9333 / 0.8444 |
| Natural Language (17) | 0.9412 / 1.0000 / 0.9412 |
| Seltene Terme (7) | 0.8571 / 1.0000 / 0.9286 |
| Common-Term-Ambiguität (14) | 0.8571 / 0.9286 / 0.9286 |
| Multi-Relevance (9) | 0.7778 / 1.0000 / 0.7407 |
| Kurze Queries (5) | 0.6000 / 0.8000 / 0.7000 |
| Längere technische Queries (5) | 0.8000 / 1.0000 / 0.7333 |
| Dokumentübergreifende Ambiguität (20) | 0.8500 / 0.9500 / 0.8333 |
| Termfrequenz-sensitive (4) | 1.0000 / 1.0000 / 0.7500 |
| Längensensitive (6) | 0.8333 / 1.0000 / 0.6944 |

### Hybrid-Ergebnisse und Kategorien

Die Hybrid-RRF-Baseline ist für v1 nicht gemessen. Auf v2 erreicht sie `0.7857 /
0.9643 / 0.8988` für Hit@1, Hit@3 und Mean Recall@3. Ihre Hit@1-Misses sind
`positioning_causes_natural`, `s02_recovery_verification`, `calibration_procedure`,
`qv1_role_short`, `service_evidence_multiple` und `vision_recovery_multiple`; der
einzige Hit@3-Miss ist `s02_recovery_verification`. Unvollständiger Recall@3 bleibt bei
`positioning_causes_natural`, `axis_encoder_short`, `s02_recovery_verification`,
`service_evidence_multiple` und `vision_recovery_multiple`.

| Kategorie (n) | Hybrid H@1/H@3/MR@3 |
| --- | --- |
| Exakte Identifier (15) | 0.8000 / 1.0000 / 0.9444 |
| Natural Language (17) | 0.7647 / 0.9412 / 0.8824 |
| Seltene Terme (7) | 1.0000 / 1.0000 / 0.9286 |
| Common-Term-Ambiguität (14) | 0.7857 / 0.9286 / 0.9286 |
| Multi-Relevance (9) | 0.6667 / 1.0000 / 0.7963 |
| Kurze Queries (5) | 0.8000 / 1.0000 / 0.9000 |
| Längere technische Queries (5) | 0.6000 / 1.0000 / 0.8333 |
| Dokumentübergreifende Ambiguität (20) | 0.7500 / 0.9500 / 0.8583 |
| Termfrequenz-sensitive (4) | 0.5000 / 1.0000 / 0.8750 |
| Längensensitive (6) | 0.5000 / 1.0000 / 0.7778 |

## Ranking-Unterschiede und Interpretation

Ausgewählte BM25-Top-3-Rankings zeigen, wo die neuen Signale helfen und wo lexikalische
Überlappung weiterhin falsch dominiert:

| Fall | BM25-Rang 1 | BM25-Rang 2 | BM25-Rang 3 |
| --- | --- | --- | --- |
| `error_code_exact` | `station_s04::chunk-002` (6.2842) | `error_codes::chunk-002` (5.5117) | `error_codes::chunk-001` (3.9496) |
| `positioning_causes_natural` | `station_s02::chunk-001` (8.5921) | `station_s02::chunk-002` (5.6584) | `maintenance::chunk-002` (2.7372) |
| `s02_recovery_verification` | `station_s02::chunk-003` (4.7327) | `troubleshooting_service::chunk-002` (4.5982) | `maintenance::chunk-002` (4.4223) |
| `calibration_procedure` | `vision_calibration::chunk-002` (5.7888) | `vision_calibration::chunk-003` (4.8377) | `vision_calibration::chunk-004` (4.5653) |
| `qv1_role_short` | `production_quality::chunk-002` (3.1451) | `vision_calibration::chunk-001` (2.3338) | `station_s04::chunk-001` (1.5720) |
| `service_evidence_multiple` | `troubleshooting_service::chunk-002` (8.5692) | `production_quality::chunk-003` (8.3476) | `maintenance::chunk-003` (5.4675) |
| `vision_recovery_multiple` | `troubleshooting_service::chunk-003` (13.0595) | `vision_calibration::chunk-001` (9.4296) | `vision_calibration::chunk-004` (8.8271) |

BM25s Hauptgewinn liegt in der Recall-Tiefe. `calibration_procedure` wechselt von
einem Hit@3-Miss unter Simple und IDF auf Rang 2, weil wiederholte passende Terme und
Length Normalization die Procedure-Passage konkurrenzfähig machen. `qv1_role_short`
bleibt auf Rang 1 falsch, ist aber wie unter IDF ein Hit@3.
`vision_recovery_multiple` behält IDFs zwei von drei relevanten Chunks und verbessert
sich gegenüber Simples einem Chunk. Die termfrequenz-sensitive Kategorie verbessert
sich deutlich bei Hit@3 und Mean Recall@3, konsistent mit den beabsichtigten Signalen
aus TF-Sättigung und Length Normalization.

Der Trade-off ist schwächere Rank-1-Präzision. `error_code_exact` wechselt von einem
korrekten IDF-Rang 1 auf Rang 2, weil die kürzere Station-Passage den passenden
Identifier wiederholt und einen stärkeren normalisierten Beitrag erhält.
`service_evidence_multiple` behält Recall@3 von 0.5, verliert aber Hit@1, weil die
Recurring-Failure-Passage mehr passende Terme sammelt als die erwarteten
Evidence-Passagen. BM25 verbessert den aggregierten Multi-Relevance Recall gegenüber
IDF nicht und reduziert dessen Hit@1.

`positioning_causes_natural` und `s02_recovery_verification` sind für diese
lexikalischen Strategien grundsätzlich schwer: Formulierungen wie "commanded
location" gegenüber "target position" sowie "prove ... ready after repair" gegenüber
"confirm homing, run one dry cycle, and inspect" teilen zu wenig unterscheidendes
Vokabular. BM25 kann fehlende Synonym- oder Bedeutungsbeziehungen nicht erzeugen.
`qv1_role_short` ist ebenfalls lexikalisch unterspezifiziert, weshalb eine spezifische
Outcome-Passage besser passt als der beabsichtigte Überblick. Mehrere verbleibende
unvollständige Multi-Relevance-Fälle drücken mehrere Intents aus, deren ergänzende
Passagen um nur drei Ergebnisplätze konkurrieren.

### Semantischer Vergleich

Die semantische Baseline verbessert die Natural-Language-Kategorie deutlich auf
`0.9412 / 1.0000 / 0.9412`, verglichen mit BM25s `0.7647 / 0.9412 / 0.8824`. Die
Verbesserungen passen zu abweichenden Formulierungen statt zu einem geänderten Corpus:
`positioning_causes_natural` setzt den erwarteten `station_s02::chunk-002` auf Rang 1
(0.6968), `s02_recovery_verification` setzt `station_s02::chunk-004` auf Rang 1
(0.5760), und `calibration_procedure` setzt `vision_calibration::chunk-003` auf Rang 1
(0.6519). BM25 setzt die erwarteten Chunks auf Rang 2, außerhalb der Top 3 und auf Rang
2.

| Fall | Erwartete Chunks | Semantic Top 3 | BM25 Top 3 |
| --- | --- | --- | --- |
| `positioning_causes_natural` | `station_s02::chunk-002`, `troubleshooting_service::chunk-002` | `station_s02::chunk-002` (0.6968), `station_s02::chunk-001` (0.6228), `station_s02::chunk-003` (0.6038) | `station_s02::chunk-001` (8.5921), `station_s02::chunk-002` (5.6584), `maintenance::chunk-002` (2.7372) |
| `s02_recovery_verification` | `station_s02::chunk-004` | `station_s02::chunk-004` (0.5760), `station_s02::chunk-001` (0.5430), `station_s02::chunk-002` (0.5113) | `station_s02::chunk-003` (4.7327), `troubleshooting_service::chunk-002` (4.5982), `maintenance::chunk-002` (4.4223) |
| `qv1_role_short` | `vision_calibration::chunk-001` | `error_codes::chunk-003` (0.5685), `station_s04::chunk-001` (0.5537), `production_quality::chunk-002` (0.5486) | `production_quality::chunk-002` (3.1451), `vision_calibration::chunk-001` (2.3338), `station_s04::chunk-001` (1.5720) |
| `calibration_procedure` | `vision_calibration::chunk-003` | `vision_calibration::chunk-003` (0.6519), `vision_calibration::chunk-002` (0.6496), `vision_calibration::chunk-004` (0.5898) | `vision_calibration::chunk-002` (5.7888), `vision_calibration::chunk-003` (4.8377), `vision_calibration::chunk-004` (4.5653) |

Semantisches Ranking ist bei exakten Identifiern schwächer (`0.7333` Hit@1 gegenüber
BM25s `0.8000`) und bei kurzen Queries (`0.6000 / 0.8000 / 0.7000` gegenüber
`0.8000 / 1.0000 / 0.9000`). `qv1_role_short` wird zu einem semantischen Hit@3-Miss,
während BM25 ihn auf Rang 2 hält. Auch den aggregierten Multi-Relevance-Recall verbessert
das semantische Modell nicht, weil ergänzende Chunks weiter um nur drei Plätze
konkurrieren. Die Score-Skalen unterscheiden sich und dienen daher nur der
Ranking-Inspektion, nicht einem direkten strategieübergreifenden Zahlenvergleich.

### Hybrid-Vergleich

Der feste RRF-Hybrid erreicht `0.7857 / 0.9643 / 0.8988` für Hit@1, Hit@3 und Mean
Recall@3. Damit behält er den besten Hit@3 bei und erhöht die Recall-Tiefe gegenüber
jeder einzelnen BM25- und Semantic-Baseline um `0.0179`. Dies zeigt sich besonders bei
exakten Identifiern (`0.9444` Mean Recall@3), Multi-Relevance (`0.7963`), längeren
technischen Queries (`0.8333`) und dokumentübergreifender Ambiguität (`0.8583`). Die
Rank-1-Präzision verbessert sich nicht: Lexikalische BM25-Evidence kann semantisch
korrekte erste Ergebnisse abwerten, und gleiche fusionierte Scores werden ohne
semantische Präferenz über `chunk_id` aufgelöst.

| Fall | Erwartete Chunks | BM25 Top 3 | Semantic Top 3 | Hybrid Top 3 (RRF) |
| --- | --- | --- | --- | --- |
| `positioning_causes_natural` | `station_s02::chunk-002`, `troubleshooting_service::chunk-002` | `station_s02::chunk-001` (8.5921), `station_s02::chunk-002` (5.6584), `maintenance::chunk-002` (2.7372) | `station_s02::chunk-002` (0.6968), `station_s02::chunk-001` (0.6228), `station_s02::chunk-003` (0.6038) | `station_s02::chunk-001` (0.032522), `station_s02::chunk-002` (0.032522), `station_s02::chunk-003` (0.030798) |
| `s02_recovery_verification` | `station_s02::chunk-004` | `station_s02::chunk-003` (4.7327), `troubleshooting_service::chunk-002` (4.5982), `maintenance::chunk-002` (4.4223) | `station_s02::chunk-004` (0.5760), `station_s02::chunk-001` (0.5430), `station_s02::chunk-002` (0.5113) | `station_s02::chunk-003` (0.032018), `station_s02::chunk-002` (0.031498), `station_s02::chunk-001` (0.031281) |
| `qv1_role_short` | `vision_calibration::chunk-001` | `production_quality::chunk-002` (3.1451), `vision_calibration::chunk-001` (2.3338), `station_s04::chunk-001` (1.5720) | `error_codes::chunk-003` (0.5685), `station_s04::chunk-001` (0.5537), `production_quality::chunk-002` (0.5486) | `production_quality::chunk-002` (0.032266), `station_s04::chunk-001` (0.032002), `vision_calibration::chunk-001` (0.031754) |
| `calibration_procedure` | `vision_calibration::chunk-003` | `vision_calibration::chunk-002` (5.7888), `vision_calibration::chunk-003` (4.8377), `vision_calibration::chunk-004` (4.5653) | `vision_calibration::chunk-003` (0.6519), `vision_calibration::chunk-002` (0.6496), `vision_calibration::chunk-004` (0.5898) | `vision_calibration::chunk-002` (0.032522), `vision_calibration::chunk-003` (0.032522), `vision_calibration::chunk-004` (0.031746) |
| `error_code_exact` | `error_codes::chunk-002` | `station_s04::chunk-002` (6.2842), `error_codes::chunk-002` (5.5117), `error_codes::chunk-001` (3.9496) | `error_codes::chunk-002` (0.8045), `station_s04::chunk-002` (0.7444), `maintenance::chunk-002` (0.6557) | `error_codes::chunk-002` (0.032522), `station_s04::chunk-002` (0.032522), `error_codes::chunk-001` (0.031258) |
| `service_evidence_multiple` | `production_quality::chunk-003`, `troubleshooting_service::chunk-004` | `troubleshooting_service::chunk-002` (8.5692), `production_quality::chunk-003` (8.3476), `maintenance::chunk-003` (5.4675) | `troubleshooting_service::chunk-004` (0.6593), `troubleshooting_service::chunk-001` (0.6158), `maintenance::chunk-003` (0.5190) | `troubleshooting_service::chunk-002` (0.032018), `maintenance::chunk-003` (0.031746), `troubleshooting_service::chunk-004` (0.031545) |

Der Vergleich zeigt komplementäre Evidence, aber keine universelle Rank-1-Lösung. Bei
`error_code_exact` wird der gleiche RRF-Score zugunsten des erwarteten Error-Code-Chunks
aufgelöst. Bei `qv1_role_short` stellt Hybrid einen Top-3-Hit wieder her, den das
Semantic Retrieval verfehlt, platziert ihn aber unter der BM25-Position. Umgekehrt ist
`s02_recovery_verification` ein Hybrid-Hit@3-Miss, obwohl Semantic allein den erwarteten
Verification-Chunk auf Rang 1 setzt: die lexikalischen Spitzenränge verdrängen ihn.
`positioning_causes_natural` fehlen weiter die zweite relevante Service-Passage und
`service_evidence_multiple` enthält weiter nur eine von zwei erwarteten Passagen. Das
sind verbleibende Grenzen bei Tiefe und Intent-Disambiguierung, kein Anlass, v2 Labels
oder den eingefrorenen Corpus zu ändern.

### Reranking-Vergleich

`Hybrid + Reranker` erreicht auf v2 `0.8214 / 1.0000 / 0.9881` für Hit@1, Hit@3 und
Mean Recall@3, gegenüber Hybrids `0.7857 / 0.9643 / 0.8988`. Hit@3-Misses entfallen;
unvollständiger Recall@3 bleibt nur bei `vision_recovery_multiple`. Nach Kategorie
erreicht der Reranker insbesondere vollständigen Recall bei Natural Language,
Rare Terms, Common-Term-Ambiguität, kurzen Queries und termfrequenz-sensitiven Fällen;
Multi-Relevance steigt auf `0.7778 / 1.0000 / 0.9630`.

`positioning_causes_natural` wechselt von Hybrid-Rang 2 für
`station_s02::chunk-002` auf Rang 1 (0.688441) und hebt zugleich die relevante
`troubleshooting_service::chunk-002` auf Rang 3. `qv1_role_short` setzt
`vision_calibration::chunk-001` auf Rang 1 (0.914100). Bei
`s02_recovery_verification` gelangt `station_s02::chunk-004` aus Hybrid-Rang 7 auf
Rang 3 (0.001280), korrigiert also den Hit@3, aber nicht Hit@1.
`calibration_procedure` behält `vision_calibration::chunk-003` auf Rang 3 (0.144749),
und `service_evidence_multiple` behält `troubleshooting_service::chunk-002` auf Rang 1
statt einer erwarteten Passage. Die Reranker-Scores sind nur innerhalb derselben Query
zum Sortieren geeignet.

Der lokale Smoke für "How do I verify that S02 is ready again after repair?" zeigte
`station_s02::chunk-004` nach Hybrid-Rang 2 auf Reranker-Rang 1 (0.714973), mit
vollständiger Source- und Chunk-Provenance.

## Bekannte Grenzen

Der Corpus bleibt bewusst klein und manuell nachvollziehbar, statt Production Scale
abzubilden. BM25 besitzt weiterhin weder Stemming, Synonyme, Phrase Model, Query
Expansion noch semantisches Verständnis. Die semantische Baseline ist Local-Only, und
der feste Hybrid besitzt weder Identifier-Boost noch gelernte Gewichte. Der erste lokale
Reranker hat kein Ensemble, keine zweite Modellvariante, kein Query Rewriting,
persistenten Index, Freshness Management oder Embedding-Routing-Policy.
`InMemoryVectorStore` wird bei der Erstellung neu gebaut und ist keine Entscheidung für
eine Vector Database. Abschnittspositions-IDs können sich nach strukturellen
Dokumentänderungen verschieben. Grounding der finalen Antwort und Qualität der Agent
Query werden durch diese Retrieval-Baseline nicht evaluiert.
