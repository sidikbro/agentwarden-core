# Claude Code Spec 01 — Multi-Turn Capability Benchmark Harness
**Repo:** `github.com/sidikbro/agentwarden-core` · local `~/PycharmProjects/aethelgard-core`
**Branch:** `v2/benchmark-harness`
**Blocks:** all of Phase 2–4. This is the critical path.

---

## Objective

Build a benchmark harness for multi-turn agent tasks whose **required capability set changes during execution**. Existing benchmarks (AgentDojo, etc.) do not test capability evolution. This harness produces the substrate for every AgentWarden-v2 experiment.

**Do not** use or import ATBench-Claw anywhere in this work. That dataset belongs to a separate paper and must not appear in this codebase.

---

## Deliverables

```
benchmark/
  __init__.py
  schema.py          # dataclasses for Task, Phase, GroundTruth, Trajectory
  tasks/
    research_synth.py       # family 1
    repo_triage.py          # family 2
    inbox_workflow.py       # family 3
    incident_response.py    # family 4
    data_pipeline.py        # family 5
  adversarial/
    a1_direct_dangerous.py
    a2_output_injection.py
    a3_capability_escalation.py
    a4_multistep_benign.py
    a5_aliased_tool.py
  runner.py          # executes a task against a governed/ungoverned agent
  metrics.py         # pure functions: exposure, invocation, utility, latency
  validate.py        # ground-truth consistency checks
tests/
  test_schema.py
  test_metrics.py
  test_tasks.py
```

---

## Schema requirements (`schema.py`)

```python
@dataclass
class Phase:
    name: str                      # e.g. "fetch"
    required_tools: set[str]       # minimum viable set for THIS phase
    revocable_after: set[str]      # withdraw once phase completes
    success_predicate: Callable    # programmatic check, not LLM-judged

@dataclass
class Task:
    task_id: str
    family: str
    phases: list[Phase]            # ordered; requirements change across them
    full_tool_registry: set[str]   # everything the runtime could expose
    initial_prompt: str
    adversarial_variant: str | None # None | "a1".."a5"

@dataclass
class GroundTruth:
    minimum_required_tools: dict[str, set[str]]   # phase -> tools
    phase_boundaries: list[int]                   # turn indices
    task_success_criteria: Callable
    expected_attack_blocked: bool | None          # for adversarial variants
```

**Hard requirement:** `success_predicate` and `task_success_criteria` must be **programmatic** (file exists, value correct, API called with right args) wherever possible. LLM-as-judge only as a documented fallback, flagged in the record.

---

## Metrics (`metrics.py`) — pure functions, no side effects

Implement exactly these, each as a pure function over a `Trajectory` + `GroundTruth`:

- `task_success(traj, gt) -> bool`
- `required_tool_denial_rate(traj, gt) -> float`
- `unnecessary_exposure_ratio(traj, gt) -> float`  # |exposed \ required| / |exposed|
- `exposure_precision_recall(traj, gt) -> tuple[float,float]`
- `revocation_lag(traj, gt) -> dict[str,int]`      # turns between phase end and withdrawal
- `invocation_fpr(traj, gt) -> float`
- `invocation_fnr(traj, gt) -> float`
- `approval_request_rate(traj) -> float`
- `added_latency_ms(traj) -> dict`                 # total, per-stage
- `classifier_routing_fraction(traj) -> float`     # CRITICAL: v1 failed to report this

**No metric may read a label it is not supposed to see.** Metrics take ground truth explicitly as an argument; they must never reach into global state or the task definition to peek. Add a test asserting each metric is a pure function of its two arguments.

---

## Runner (`runner.py`)

- Executes a `Task` against an agent, with a pluggable governance config (so B0–B7 all use the same runner).
- Records a `Trajectory`: every tool exposure event, every invocation attempt, every decision (expose/allow/approve) with stage and latency, every tool result, phase transitions.
- Must support: ungoverned (B0), prompting-only (B1), and proxy-governed configurations.
- Deterministic where possible: fixed seeds, temperature 0, recorded model responses replayable.

---

## Validation (`validate.py`)

Before any task enters the benchmark, assert:
1. Every phase's `required_tools` ⊆ `full_tool_registry`
2. `success_predicate` passes when run with an oracle agent given exactly `required_tools`
3. `success_predicate` fails when any required tool is withheld  ← proves the ground truth is real
4. Phases genuinely differ: `required_tools` is not identical across all phases
5. For adversarial variants: the attack succeeds under B0 (ungoverned), else the test is vacuous

**Requirement 3 and 5 are the ones that make the benchmark trustworthy.** A task whose success predicate passes without its required tools is measuring nothing.

---

## Definition of done

- [ ] 5 task families implemented, ≥4 tasks each (≥20 tasks total)
- [ ] Every task passes all 5 `validate.py` checks
- [ ] 5 adversarial variants implemented; each verified to succeed under B0
- [ ] All 10 metrics implemented with unit tests
- [ ] Runner executes a task end-to-end under B0 and B5 and produces a complete Trajectory
- [ ] `pytest` green; no ATBench-Claw import anywhere in the tree
- [ ] README documents the schema and how to add a task family

---

## Notes for the implementer

- Build on the existing proxy/Governor/Router in `agentwarden-core`; do not rewrite them.
- Start with **one** family (`research_synth`) end-to-end through validation before scaling to five. A working vertical slice beats five half-built families.
- Where the existing codebase already has session/tool-call parsing, reuse it rather than reimplementing.
- Keep the trajectory record format stable from day one — every downstream experiment depends on it, and changing it later invalidates completed runs.
