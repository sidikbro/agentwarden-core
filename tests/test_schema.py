from __future__ import annotations

from benchmark.schema import ExposureEvent, Trajectory, exposed_tools_at


def test_exposed_tools_at_reconstructs_full_set_without_replay():
    traj = Trajectory(task_id="t", baseline="B0", session_id="s")
    traj.exposure_events = [
        ExposureEvent(turn=0, phase="search", tool_name="search_web",
                      action="expose", exposed_tools=frozenset({"search_web"})),
        ExposureEvent(turn=3, phase="fetch", tool_name="fetch_url",
                      action="expose", exposed_tools=frozenset({"search_web", "fetch_url"})),
        ExposureEvent(turn=6, phase="analyze", tool_name="search_web",
                      action="revoke", exposed_tools=frozenset({"fetch_url"})),
    ]

    assert exposed_tools_at(traj, -1) == frozenset()
    assert exposed_tools_at(traj, 0) == frozenset({"search_web"})
    assert exposed_tools_at(traj, 4) == frozenset({"search_web", "fetch_url"})
    assert exposed_tools_at(traj, 6) == frozenset({"fetch_url"})
    assert exposed_tools_at(traj, 100) == frozenset({"fetch_url"})


def test_exposed_tools_at_order_independent():
    """Events out of order in the list must still reconstruct correctly —
    the helper sorts by turn rather than trusting insertion order."""
    ev_early = ExposureEvent(turn=0, phase="p", tool_name="a", action="expose",
                              exposed_tools=frozenset({"a"}))
    ev_late = ExposureEvent(turn=5, phase="p", tool_name="b", action="expose",
                             exposed_tools=frozenset({"a", "b"}))
    traj = Trajectory(task_id="t", baseline="B0", session_id="s",
                       exposure_events=[ev_late, ev_early])
    assert exposed_tools_at(traj, 5) == frozenset({"a", "b"})
