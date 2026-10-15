# Demo User Visibility

Start a **new chat** for each check. Switch users in the header account menu; no password is needed in Demo Auth Mode.

| User | Clearance | Roles |
| --- | --- | --- |
| demo-public | PUBLIC | — |
| demo-internal | INTERNAL | — |
| demo-confidential | CONFIDENTIAL | — |
| demo-restricted | RESTRICTED | — |
| demo-admin | PUBLIC | MODEL_ADMIN |

## Expected visibility

| User | Stations | Products |
| --- | --- | --- |
| demo-public | S01, S05 | P4101, P4102 |
| demo-internal | S01, S02, S03, S05 | P4101, P4102, P4900, P4901 |
| demo-confidential | S01, S02, S03, S04, S05, S06 | P4101, P4102, P4711, P4801, P4802, P4805, P4811, P4900, P4901 |
| demo-restricted | S01, S02, S03, S04, S05, S06, S07, S08 | P4101, P4102, P4711, P4801, P4802, P4805, P4811, P4900, P4901, P9001, P9002 |
| demo-admin | S01, S05 | P4101, P4102 |

## Quick manual smoke tests

1. Switch through the five users above. Each time start a new chat and ask **“Welche Stationen kennst du?”**. Expect exactly that user's station set and a successful `list_stations` step.
2. Repeat with **“Welche Produkte kennst du?”**. Expect the product set and `list_products`.
3. In a new chat ask **“S07”**: visible for demo-restricted; neutral unavailable for public, internal, confidential and admin.
4. Configuration is enabled for demo-admin and disabled for demo-restricted. Admin does not increase data clearance.

Explicit product discovery presents the complete currently authorized product set,
in Factory product-ID order, from the typed `list_products` observation. Each product
keeps its available latest status; an unavailable optional status remains unknown.
This inventory is rendered deterministically in the answer, even when the model
mentions fewer products or its narrative is replaced by the safe fallback. Trusted
reference presentation remains separately bounded to 12 identifiers; that budget is
not an inventory limit. The existing 8,000-character answer bound remains in force:
larger inventories explicitly say that the displayed result is partial.

## Seed inventory

| Classification | Stations | Products | Example document |
| --- | --- | --- | --- |
| PUBLIC | S01, S05 | P4101, P4102 | doc-958096ad21a480be — Factory Overview |
| INTERNAL | S02, S03 | P4900, P4901 | doc-ebb5dc762870b7b0 — Operator Handbook |
| CONFIDENTIAL | S04, S06 | P4711, P4801, P4802, P4805, P4811 | doc-s04quality09procedure — S04 QUALITY-09 Troubleshooting Procedure |
| RESTRICTED | S07, S08 | P9001, P9002 | doc-p9001s07commission — P9001 S07 Restricted Commissioning Notes |

The existing maintenance ticket `MT-S02-20260117` is CONFIDENTIAL; process parameter `robot_trajectory_limit` at S03 is RESTRICTED. No extra tickets or hardware actions are required.

Complete neutral discovery forms use the server's clearance as a **data-return ceiling**, conservatively labeling the run for all data it may receive. This does not classify arbitrary user text by clearance: unknown/mixed text remains RESTRICTED, and sensitive identifiers/context never downgrade. PostgreSQL RLS filters entities before the model sees evidence. [Deterministic seed](../../src/industrial_ai_agent/infrastructure/persistence/demo_seed.py) upserts stable fixtures without deleting unrelated runtime data.
