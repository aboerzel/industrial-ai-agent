// One registry and unchanged required assertions for both execution environments.
import { JOURNEYS } from "./run-e2e-journey.mjs";
import { assertionPlan } from "./journey-assertions.mjs";

console.log(JSON.stringify(Object.entries(JOURNEYS).map(([id, definition]) => ({
  id, assertions: assertionPlan(definition),
}))));
