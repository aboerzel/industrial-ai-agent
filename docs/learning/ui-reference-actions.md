# UI Reference Actions

Reference buttons send ordinary `POST /api/v1/runs` requests with `message`,
`response_language` and the current `investigation_id`. There is no structured
reference-action shortcut. Existing `next_steps` are textual follow-ups; the structured
internal diagnostic endpoint serves a different fixed two-entity use case.
The browser never supplies authority through a reference or origin flag.

These complete, already admitted neutral forms are canonical:

| Reference/action | DE | EN | First authorized capability |
| --- | --- | --- | --- |
| Station investigate / overview | `Prüfe den aktuellen Status von Station S04.` | `What is the current status of station S04?` | Machine status, or safe station overview when only that read is admitted |
| Station status | `Prüfe den aktuellen Status von Station S04.` | `What is the current status of station S04?` | Same bounded station read |
| Product investigate | `Untersuche Produkt P4901.` | `Investigate product P4901.` | Product overview |
| Product history | `Zeige die Produkthistorie von P4901.` | `Show me the production history for P4901.` | Product history |
| Fault investigate / documentation | `Untersuche QUALITY-09.` | `Investigate QUALITY-09.` | Documentation search for the exact fault code |
| Ticket inspect | `Zeige das Wartungsticket MT-S02-20260117.` | `Show ticket MT-S02-20260117.` | Maintenance ticket read |

Station reference buttons provide bounded current-state navigation; full typed station
troubleshooting keeps its existing RCA requirements. Explicit status reads use the
proportional current-state requirement (PUBLIC retains its safe overview contract).
Non-station reference reads do not create a station RCA ledger from an embedded ID
fragment, such as `S02` inside ticket `MT-S02-20260117`.
Fault investigation and documentation buttons share the supported fault-documentation
path. Document Open/Download retain the authorized document endpoint and server filename;
they do not create an agent prompt. Copy does not submit.

After server classification and authorization, the bounded graph parses only these
complete forms and schedules the first read through normal guarded dispatch, retaining
the exact canonical identifier. The model does not infer this first target. Later calls
remain limited to relevant read capabilities and cannot replace the primary entity.
Station documentation remains subject to ADR-020's trusted state/fault evidence.
Unknown and above-clearance entities retain existing non-disclosing semantics. Typed
identical forms behave identically; reference origin is never trusted. Extra prose
does not match this parser and retains conservative classification.

Persisted investigation ownership, classification joins, RLS, capability admission,
model egress, approval guards and browser generation invalidation remain authoritative.
Self-contained reference reads keep their persisted investigation and server-owned
context classification; only their LLM projection omits earlier conversational prose
and uses the explicit request plus fresh authorized observations.
Reload restores references only from authorized API history. Identity invalidation
removes references and open menus before refresh.
