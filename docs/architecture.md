# CoffeeClaw Architecture

## Current Layout

The repository currently uses a thin shared layer plus PRD-aligned domain directories:

- `src/core/`: app factory, settings, and shared state access
- `src/api/`: HTTP routes, dependencies, and schemas
- `src/observability/`: logging, request context, and exception handling
- `src/infrastructure/`: resource bootstrap for external services
- `src/services/`: small cross-cutting application services used by the API surface
- `src/runtime/`, `src/orchestrator/`, `src/workflow/`, `src/tools/`, `src/memory/`, `src/model/`: domain modules that will absorb business capabilities in later tasks

## Layering Rules

1. `src/main.py` only creates the FastAPI app.
2. `src/core/` stays thin. It wires modules together but should not accumulate business logic.
3. `src/observability/` owns request-scoped logging, exception translation, and later tracing/metrics.
4. `src/infrastructure/` is limited to bootstrap and teardown of shared external resources.
5. New platform capabilities should prefer PRD domain modules over `services/` or `infrastructure/`.

## Near-term Direction

- Runtime lifecycle and checkpoints move into `src/runtime/`
- Redis/Postgres usage for memory moves into `src/memory/`
- Model access and routing move into `src/model/`
- `src/services/` should remain small; it is not the primary home for platform logic
