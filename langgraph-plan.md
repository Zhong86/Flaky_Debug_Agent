# LangGraph Plan — Flaky Debug Agent

## Overview

Build the LangGraph orchestration layer for the Flaky Debug Agent. The graph is triggered after a CI failure is received. It runs through six nodes — `check_flaky`, `debug_agent`, `code_fix`, `retest_flaky`, `documents`, and `output` — and is housed in `backend/src/backend/graph/`. All agent/LLM calls are **dummy stubs** for now. The graph lives as a standalone runnable module (no FastAPI integration yet).

`langgraph` is added as a project dependency and all loose `requirements.txt` entries are consolidated into `pyproject.toml`.

---

## Sub-Task 1 — Update `pyproject.toml` with `langgraph` and consolidate `requirements.txt`

**Status:** `[ ] pending`

**Intent:**  
Add `langgraph` to the project's declared dependencies and move every pinned package from `requirements.txt` into `pyproject.toml` so there is a single source of truth for dependencies. `requirements.txt` can then be removed or left as a lock-file artifact.

**Expected Outcomes:**
- `pyproject.toml` `[project] dependencies` includes `langgraph`.
- All packages currently listed in `requirements.txt` appear in `pyproject.toml` (either as direct deps or under a new `[dependency-groups]` section).
- `requirements.txt` is deleted (or clearly noted as redundant).

**Todo List:**
1. Open `backend/pyproject.toml` and review current `dependencies` and `[dependency-groups]`.
2. Add `langgraph` to `[project] dependencies`.
3. Move all pinned packages from `requirements.txt` into a `[dependency-groups] prod` or inline them in `[project] dependencies` as appropriate.
4. Delete `backend/requirements.txt`.

**Relevant Context:**
- [`backend/pyproject.toml`](backend/pyproject.toml)
- [`backend/requirements.txt`](backend/requirements.txt)

---

## Sub-Task 2 — Define `GraphState`

**Status:** `[ ] pending`

**Intent:**  
Create the shared state schema that flows through every node in the graph. Using a `TypedDict` (LangGraph standard) keeps it lightweight and compatible with LangGraph's state management.

**Expected Outcomes:**
- A `GraphState` TypedDict is defined at `backend/src/backend/graph/state.py`.
- Contains exactly these fields:
  - `github_payload: dict`
  - `logs: str`
  - `is_flaky: bool`
  - `debug_findings: str`
  - `fix_applied: bool`
  - `retest_passed: bool`
  - `document: str`
  - `callback_url: str`

**Todo List:**
1. Create `backend/src/backend/graph/state.py`.
2. Define `GraphState` as a `TypedDict` with all eight fields.

**Relevant Context:**
- [`backend/src/backend/graph/`](backend/src/backend/graph/) — currently empty directory.

---

## Sub-Task 3 — Implement the six graph nodes

**Status:** `[ ] pending`

**Intent:**  
Create each node as a plain Python function that accepts and returns a `GraphState`-compatible dict. All agent/LLM behaviour is stubbed — nodes only update the relevant state fields and print a trace line so execution is observable.

**Expected Outcomes:**
- `backend/src/backend/graph/nodes.py` exists with six functions.
- Each function signature is `(state: GraphState) -> dict`.
- Behaviour per node:

| Node | Stub behaviour |
|---|---|
| `check_flaky` | Hardcodes `is_flaky: True`, prints trace |
| `debug_agent` | Sets `debug_findings` to a placeholder string, prints trace |
| `code_fix` | Sets `fix_applied: True`, prints trace |
| `retest_flaky` | Hardcodes `retest_passed: True`, prints trace |
| `documents` | Dummy LLM summary stub — writes `report_{timestamp}.md` to `flaky_debug/success/` if `retest_passed` else `flaky_debug/fail/` (both relative to **project root**); sets `document` to the file path |
| `output` | Logs `callback_url` and a state summary to stdout |

**Todo List:**
1. Create `backend/src/backend/graph/nodes.py`.
2. Implement all six node functions, importing `GraphState` from `state.py`.
3. In `documents`: resolve the project root (two levels up from the `graph/` package), create `flaky_debug/success/` or `flaky_debug/fail/` if it doesn't exist, write `report_{timestamp}.md`, set `state["document"]` to the full path.
4. In `output`: print `callback_url` and a readable summary of key state fields.

**Relevant Context:**
- [`backend/src/backend/graph/state.py`](backend/src/backend/graph/state.py) — created in Sub-Task 2.

---

## Sub-Task 4 — Build and wire the LangGraph graph

**Status:** `[ ] pending`

**Intent:**  
Assemble the `StateGraph`, register all nodes, and add edges (including the conditional branch after `check_flaky`). Compile it into a runnable graph and expose it as `graph` from the module.

**Expected Outcomes:**
- `backend/src/backend/graph/graph.py` exists.
- Graph structure matches the README flow — post CI-failure path only:

```
check_flaky → (is_flaky=True) → debug_agent → code_fix → retest_flaky → documents → output → END
             ↘ (is_flaky=False) → END
```

- `graph` (compiled) is importable from `backend.graph.graph`.

**Todo List:**
1. Create `backend/src/backend/graph/graph.py`.
2. Import `StateGraph`, `END` from `langgraph.graph`.
3. Import `GraphState` from `state.py` and all six node functions from `nodes.py`.
4. Add each node to the `StateGraph`.
5. Set `check_flaky` as the entry point.
6. Add a conditional edge from `check_flaky` using `is_flaky` — routes to `debug_agent` if True, else `END`.
7. Add linear edges: `debug_agent → code_fix → retest_flaky → documents → output → END`.
8. Compile and assign to `graph`.

**Relevant Context:**
- [`backend/src/backend/graph/nodes.py`](backend/src/backend/graph/nodes.py) — created in Sub-Task 3.
- [`backend/src/backend/graph/state.py`](backend/src/backend/graph/state.py) — created in Sub-Task 2.

---

## Sub-Task 5 — Add `__init__.py` and a `__main__` entry point

**Status:** `[ ] pending`

**Intent:**  
Make the graph package importable and runnable as a standalone module (`python -m backend.graph`) with a minimal hardcoded input so the full graph can be exercised end-to-end without FastAPI.

**Expected Outcomes:**
- `backend/src/backend/graph/__init__.py` exports `graph` and `GraphState`.
- Running `python -m backend.graph` from `backend/` executes the graph with a dummy payload and prints node traces to stdout.
- A `flaky_debug/success/` directory and a stub `.md` document are created on first run.

**Todo List:**
1. Create/update `backend/src/backend/graph/__init__.py` to re-export `graph` and `GraphState`.
2. Create `backend/src/backend/graph/__main__.py` with a hardcoded `initial_state` dict and an `asyncio.run` or sync `graph.invoke` call.

**Relevant Context:**
- [`backend/src/backend/graph/graph.py`](backend/src/backend/graph/graph.py) — created in Sub-Task 4.

---

## Notes for Implementation

- LangGraph `StateGraph` uses `TypedDict` as the state schema — no need for a custom reducer unless fields need merging logic (they don't here).
- The conditional router after `check_flaky` should be a small lambda or named function that reads `state["is_flaky"]`.
- `documents` node should use `os.makedirs(..., exist_ok=True)` before writing. The project root is resolved via `Path(__file__).parents[5]` or by walking up to the repo root — confirm the correct relative depth at implementation time.
- Keep all node functions synchronous for now — async can be added when real LLM calls land.
