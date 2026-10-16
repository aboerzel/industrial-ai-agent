"""The local browser registry must use the current conservative request contract."""

import json
import subprocess
from pathlib import Path

import pytest

from industrial_ai_agent.agent.run_classification_policy import (
    AgentRunClassificationPolicy,
    RunClearanceDeniedError,
)
from industrial_ai_agent.infrastructure.api.demo_sessions import DemoSessions

ROOT = Path(__file__).resolve().parents[2]


def test_registered_typed_journeys_respect_server_classification_without_model_calls():
    command = "import { JOURNEYS } from './frontend/scripts/run-e2e-journey.mjs'; process.stdout.write(JSON.stringify(JOURNEYS));"
    journeys = json.loads(
        subprocess.check_output(
            ["node", "--input-type=module", "-e", command], cwd=ROOT, text=True
        )
    )
    policy = AgentRunClassificationPolicy()
    users = DemoSessions().users
    assert len(journeys) == 12
    for name, journey in journeys.items():
        context = users[f"demo-{journey['clearance'].lower()}"].security_context()
        for step in journey["steps"]:
            if step["kind"] == "switch-user":
                context = users[step["username"]].security_context()
            if step["kind"] != "typed":
                continue
            if step["expected"] == "ATTENTION":
                with pytest.raises(RunClearanceDeniedError):
                    policy.resolve_request(step["prompt"], security_context=context)
            else:
                try:
                    resolved = policy.resolve_request(
                        step["prompt"],
                        security_context=context,
                        trusted_context_classification=context.clearance,
                    )
                except RunClearanceDeniedError:
                    pytest.fail(
                        f"Unsupported harness prompt in {name}: {step['prompt']}"
                    )
                assert resolved.data_classification <= context.clearance, (name, step)
