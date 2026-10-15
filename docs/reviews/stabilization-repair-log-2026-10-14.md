# Stabilization Repair Log

## Iteration 1

Baseline: `D:/Freelance/industrial-ai-agent`, branch `main`, HEAD
`67c35b91e853cbd334c9be4c7c1dbe480d78ca1a`. No staged, unstaged or nonignored
untracked files at entry. Initial tracked-file SHA-256 manifest, index, containers,
image IDs and retained volume names are archived under
`evals/results/stabilization-2026-10-14/` (ignored).

Safety: no commit, push, external deployment, cloud inference, protected runtime action,
volume deletion, global prune or destructive Git command. Compose `down --timeout 30`
removes project containers/network only. All twelve project-labelled volumes retained,
including the older `postgres-data` volume. Unrelated `ollama` remains untouched.

Authoritative commands: `scripts/run-quality-gate.ps1 FAST`,
`scripts/run-quality-gate.ps1 INTEGRATION`, full `pytest tests`,
`npm --prefix frontend run test:e2e:fixtures`, clean Compose rebuild/readiness,
Ruff/format, incremental secret scan, offline wheel build, `pip check`, JS syntax,
local documentation links/translations, environment key order and `git diff --check`.
Live model/action smoke helpers are excluded by the task's safety contract;
REAL_MODEL_E2E = NOT_RUN. Fake models and disposable databases cover deterministic
orchestration, RLS and action guarantees.

First results: FAST backend 1,525 passed / one platform skip; frontend 252 passed;
Chromium fixtures 41 passed; complete Python suite 1,663 passed / one platform skip.
Wheel, dependency metadata, 38 JS syntax checks and Compose configuration passed.
Environment templates contain 43 matching ordered keys without duplicates.

No reproduced blocking product/test/security defect. Evidence-helper invocation
corrections are recorded as harness setup, not product repair attempts: same-origin
header added to the read-only HTTP probe; PowerShell secret checker corrected to preserve
regex captures and allow reading active/empty logs; toolbar whitespace normalized;
existing account-control helper reused to avoid toggling an already visible user list;
read-only SQL probe corrected to the actual singular table names. First helper output
and pre-readiness smoke results are retained. No production behavior changed.

Complete iteration result: seven clean application builds, 20/20 healthy services,
zero restarts, 123 integration passes, all exact read-only station/product RLS subsets,
five live browser identities and all configured quality gates PASS. Loki initially
returns 503 and reaches readiness after nine polls (EXPECTED_STARTUP_WARNING, LOW).
Factory/RCA export failures cease after Collector startup. Optional Grafana provisioning
directory messages and retained Tempo incomplete WAL recovery are LOW runtime notes.
Deliberate test constraint violations are EXPECTED_NEGATIVE_TEST. No FLAKY classification
or product repair attempt. Dependency/model artifact downloads are external package
traffic, not external model inference.

## Unresolved after 3 attempts

None.

## Final cycle

Phase C repeated the complete clean rebuild, startup, readiness, all tests, browser,
integration, quality/build, exact visibility probes and full-service logs from scratch.
Results match iteration 1: 1,663 full Python passes / one Windows skip; 123 separate
integration passes; 252 frontend passes; 41 Chromium fixture passes; seven fresh images;
20 healthy services; zero restarts. Existing tracked-file hash deviations: zero.
No unresolved blocker or new repairable defect. Final results are recorded in
[Full Verification](full-verification-2026-10-14.md). The independent review starts only
after this separate final clean cycle and hash freeze. REAL_MODEL_E2E = NOT_RUN.
