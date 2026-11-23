# ADR-001: Postgres task store

**Status:** Proposed (2026-11-23)

## Context

<!-- why a decision is needed: the forces and constraints -->

## Decision

Tasks are stored in Postgres via psycopg 3, one connection per call, schema applied by the service at start from an ordered migration list

## Consequences

<!-- what becomes easier or harder, what a later change must keep -->
