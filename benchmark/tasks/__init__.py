"""Benchmark task families.

Structural note, load-bearing for how any result is reported (human
review finding, 2026-09-10 — see docs/v2/BENCHMARK_EXPANSION_MANIFEST.md
and EXPERIMENTAL_PLAN_v0.2.md §4b): each family module is one distinct
task STRUCTURE (a genuinely different workflow shape). Each family's
VARIANTS beyond the first (v2, v3, ...) are WITHIN-family perturbations
of that same structure — a different file format, transport, or an
inserted side-effect step, not a different workflow. They are real and
useful for testing robustness to format/transport variation and for the
task-evolution/staleness question (a distractor tool becoming load-
bearing), but they are not independent data points for any claim that
needs to hold ACROSS task structures (e.g. "does B6 beat B3 in general,"
not "does B6 beat B3 on research-report-writing specifically").

Concretely: 5 families x up to 3 variants = 13 instances today, but only
5 genuinely distinct structures. A result reported as "N=13" without
this caveat overstates independence eightfold. Use `cluster_summary()`
below in any report that presents a top-line instance count.
"""
from __future__ import annotations


def cluster_summary(families: list) -> str:
    """One-line, honest description of what a set of families' instances
    actually are: N structures (clusters) and N total instances, with the
    perturbation count spelled out so a reader can't mistake one for the
    other. Every report script that prints a top-line "N=" figure over
    benchmark instances should call this rather than just len(INSTANCES).
    """
    n_structures = len(families)
    n_instances = sum(len(f.VARIANTS) for f in families)
    n_perturbations = n_instances - n_structures
    return (
        f"{n_structures} task structures (clusters), {n_instances} total instances "
        f"({n_perturbations} within-family perturbations) — cross-task-structure "
        f"claims are effectively N={n_structures}, not N={n_instances}"
    )
