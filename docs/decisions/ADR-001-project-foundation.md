# ADR-001: Project Foundation

## Status

Accepted

## Context

The project is intended to build practical Agentic / Applied AI engineering skills using an industrial troubleshooting scenario.

A major risk is introducing too many frameworks and abstractions before the underlying mechanics are understood.

The repository should therefore support incremental development from deterministic Python code toward increasingly agentic and distributed capabilities.

## Decision

Use Python 3.12+ with a `src` package layout.

Separate the code into the following architectural areas:

* `domain`
* `tools`
* `agent`
* `infrastructure`

Use:

* Pydantic for structured boundaries
* pytest for testing
* Ruff for linting and formatting

Do not introduce an agent framework, MCP framework, vector database, or distributed architecture in the initial project stage.

Important architectural decisions will be documented as ADRs.

## Alternatives

### Start directly with LangGraph or another agent framework

Rejected for the initial stage because it would hide important agent mechanics and add abstraction before it is necessary.

### Build the complete MCP target architecture immediately

Rejected because it would increase infrastructure complexity before basic agent behavior and tool design are established.

### Use a flat module structure

Rejected because the project is expected to evolve into a larger reference implementation.

## Consequences

Positive:

* important mechanics remain visible
* architecture can evolve deliberately
* easier testing
* good separation between domain and AI infrastructure
* suitable for learning and portfolio use

Negative:

* some code may later be replaced by framework abstractions
* early implementation may be more explicit than strictly necessary
