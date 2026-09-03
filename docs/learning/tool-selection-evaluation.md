# Tool Selection Evaluation Baseline

## Purpose

The baseline measures the first LLM decision made by `TroubleshootingAgent` against the
versioned dataset
`evals/datasets/troubleshooting_tool_selection_v1.jsonl`. Each case is evaluated with a
fresh message context and contains a stable `case_id`, a natural-language `user_input`,
an `expected_tool`, and exact `expected_arguments`.

The initial dataset contains twelve balanced cases: six for `get_product_history` and
six for `get_machine_status`. It includes English and German formulations and a distinct
product or station identifier in every case.

## Metrics

The runner reports two deterministic exact-match metrics:

* **Tool Selection Accuracy** is the share of cases with exactly one tool call whose
  name matches `expected_tool`.
* **Argument Accuracy** is the share of all cases with exactly one call, the correct
  tool, and an argument object exactly equal to `expected_arguments`.

Argument Accuracy is deliberately stricter: a response with the wrong tool cannot
receive argument credit. A missing or multiple tool call scores as incorrect for both
metrics. The structured per-case output retains the expected and actual tool,
arguments, tool-call count, both scores, and any execution error.

This baseline does not evaluate tool execution, tool results, final-answer quality,
grounding, latency, token usage, cost, or LLM-as-a-Judge quality.

## Manual Run

Start the endpoint configured for the selected Model Profile. For the initial local
`troubleshooting` profile, start Ollama and ensure `qwen3.5:9b` is available. Then run:

```powershell
python -m evals.run_tool_selection --profile troubleshooting
```

The report is written as JSON to standard output. To retain a local result explicitly:

```powershell
python -m evals.run_tool_selection `
  --profile troubleshooting `
  --output evals/results/troubleshooting.json
```

Files below `evals/results/` are ignored by Git so generated runs are not versioned
accidentally. The dataset and Model Profile mapping remain versioned. Review a result
deliberately before force-adding it as a curated baseline artifact.

## Interpretation

An accuracy of `1.0` means all twelve cases matched exactly for that metric. Compare
the per-case records when a score is lower: selection failures indicate routing
problems, while a correct tool with `arguments_correct=false` isolates extraction
errors. Temperature `0` reduces variation but does not make every LLM backend perfectly
deterministic, so repeated runs can still be useful when assessing stability.
