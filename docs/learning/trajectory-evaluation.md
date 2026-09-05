# Troubleshooting Trajectory Evaluation

## Purpose and Separation

The trajectory evaluation measures complete real runs of the bounded LangGraph MCP
agent. It complements, but does not replace, the existing
first-decision evaluation:

* The first-decision evaluation asks whether the model initially selected the expected
  tool with the expected arguments. It does not execute tools.
* The trajectory evaluation asks whether the agent followed the complete expected tool
  sequence and terminated with the expected status.

Dataset loading and validation, deterministic scoring, real-agent execution, and JSON
reporting remain separate functions. No general evaluation framework is introduced.

## Dataset

`evals/datasets/troubleshooting_trajectory_v1.jsonl` is versioned with the repository.
Each independent case contains:

* a stable `case_id`;
* the natural-language `user_input`;
* an ordered `expected_trajectory` of exact tool names and structured arguments;
* an `expected_status` such as `SUCCESS`.

The initial ten cases cover a direct answer without a tool, single product-history
lookups, single machine-status lookups for the available demo stations, and two-step
product-history-to-machine-status investigations supported by the deterministic demo
data. No `LIMIT_REACHED` case is included yet because the current data provides no
natural troubleshooting task that should require more than three successful calls.

`AgentRunResult.executed_tool_calls` exposes the normalized, actually executed
trajectory without provider-specific call IDs or SDK types. The final answer is also
recorded in the report, but its natural-language quality is not scored in this version.

## Metrics

All metrics use deterministic structured comparisons:

* **Task Success Rate** is the share of cases with both an exact trajectory and the
  expected termination status.
* **Exact Trajectory Accuracy** is the share of cases whose actual trajectory has the
  same length, order, tool names, and exact argument objects as the expected trajectory.
* **Tool Call Accuracy** compares each positional slot exactly. For each case, the
  number of slots is `max(expected_tool_calls, actual_tool_calls)`. A slot is correct
  only when both calls exist at that position and their tool name and arguments match
  exactly. The aggregate metric is
  `sum(correct positional slots) / sum(all positional slots)`. This penalizes missing,
  additional, shifted, incorrectly named, and incorrectly parameterized calls. If a
  dataset contains no tool-call slots at all, the metric is defined as `1.0`.
* **Termination Accuracy** is the share of cases whose actual `AgentRunStatus` equals
  `expected_status`.

Each result also reports `expected_tool_calls` and `actual_tool_calls`. The aggregate
report lists case IDs with missing or additional calls, and every failed record retains
expected and actual trajectories for diagnosis.

These metrics do not evaluate semantic final-answer quality, grounding, unsupported
claims, latency, token usage, cost, or LLM-as-a-Judge quality.

## Manual Run

Start the endpoint configured for the selected Model Profile. For the initial local
`local_quality` profile, start Ollama and ensure `qwen3.5:9b` is available. Then run:

```powershell
python -m evals.run_trajectory --profile local_quality --mcp-transport stdio
```

To retain a local JSON report explicitly:

```powershell
python -m evals.run_trajectory `
  --profile local_quality `
  --mcp-transport stdio `
  --output evals/results/local_quality-trajectory.json
```

Generated files below `evals/results/` are ignored by Git. The dataset, configuration,
and scoring code remain versioned.

## Interpretation

Start with Task Success Rate to see how many complete runs met both structural
requirements. Compare it with Exact Trajectory Accuracy and Termination Accuracy to
separate routing failures from termination failures. Tool Call Accuracy shows partial
positional correctness, while the expected and actual call counts expose over-calling
and under-calling directly. Inspect every failed `case_id`; a non-perfect score is a
baseline to analyze, not a reason to weaken ground truth or scoring.
