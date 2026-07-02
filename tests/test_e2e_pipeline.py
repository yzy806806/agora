"""End-to-end pipeline tests for the Agora self-driving system.

These tests verify the full pipeline integration:
  1. Project lifecycle (start → heartbeat config → stop)
  2. Heartbeat trigger path (leader_loop spawns agent, detects PROJECT_COMPLETE)
  3. Full discussion flow (raise motion → driver runs → chair/speakers/vote/summary)
  4. Kanban task lifecycle hooks (claimed, completed, blocked)

The real pipeline spawns Hermes subprocesses. These tests mock the
subprocess layer but exercise all real Agora code paths — project_planner,
leader_loop, DiscussionDriver, hooks, worker_manager, motions DB.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure /root/agora is on sys.path
_AGORA_ROOT = Path(__file__).resolve().parent.parent
if str(_AGORA_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGORA_ROOT))

# Pre-import agora.storage at module level (same pattern as test_motions.py)
from agora.storage import motions as _motions  # noqa: E402


# --------------------------------------------------------------------------- #
#  Shared fixtures                                                            #
# --------------------------------------------------------------------------- #

@pytest.fixture()
def temp_hermes_home(tmp_path, monkeypatch):
    """Set up an isolated Hermes home for E2E tests.

    Points HERMES_KANBAN_DB to a temp path so all Agora registries
    (workers, projects, motions) live under tmp_path and never touch
    the real ~/.hermes.
    """
    hermes_home = tmp_path / "hermes"
    hermes_home.mkdir()

    # Agora uses HERMES_KANBAN_DB's parent as global root
    kanban_db = hermes_home / "kanban.db"
    monkeypatch.setenv("HERMES_KANBAN_DB", str(kanban_db))

    # Patch motions DB path to use the same isolated root
    from agora.storage import motions
    db_path = hermes_home / "agora" / "motions.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(motions, "_agora_db_path", lambda: db_path)

    return hermes_home


@pytest.fixture()
def mock_worker(temp_hermes_home):
    """Create a fake worker registry entry for testing."""
    from agora.storage import motions
    # Ensure motions DB is initialized
    conn = motions._connect()
    conn.close()

    workers_dir = temp_hermes_home / "agora" / "workers"
    workers_dir.mkdir(parents=True, exist_ok=True)

    worker_data = {
        "name": "test-leader",
        "display_name": "Test Leader",
        "role": "leader",
        "is_leader": True,
        "profile_dir": str(temp_hermes_home / "profiles" / "test-leader"),
        "model": "inherited",
        "clone_from": "default",
        "projects": [],
        "session_ids": {},
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    worker_file = workers_dir / "test-leader.json"
    worker_file.write_text(json.dumps(worker_data, indent=2))

    # Also create the profile directory
    (temp_hermes_home / "profiles" / "test-leader" / "memories").mkdir(parents=True, exist_ok=True)

    return worker_data


# --------------------------------------------------------------------------- #
#  E2E Test 1: Project lifecycle                                              #
# --------------------------------------------------------------------------- #

class TestProjectLifecycle:
    """Verify start_project creates registry, configures heartbeat, stop works."""

    def test_start_project_creates_registry(self, temp_hermes_home, mock_worker):
        """start_project writes a project JSON with correct fields."""
        from project_planner import start_project, get_project

        # Mock cron creation (we don't want real cron jobs)
        with patch("project_planner._create_heartbeat_cron", return_value="cron-fake-id"):
            result = start_project(
                project_name="e2e-test",
                workdir="/tmp/e2e-workdir",
                goal="Test the pipeline",
                heartbeat_member="test-leader",
                heartbeat_minutes=5,
            )

        assert result["status"] == "started"
        proj = result["project"]
        assert proj["name"] == "e2e-test"
        assert proj["status"] == "active"
        assert proj["goal"] == "Test the pipeline"
        assert proj["heartbeat_member"] == "test-leader"
        assert proj["heartbeat_minutes"] == 5
        assert proj["heartbeat_cron_id"] == "cron-fake-id"
        assert proj["board"] == "agora-e2e-test"

        # Verify the project file was written to disk
        loaded = get_project("e2e-test")
        assert loaded is not None
        assert loaded["name"] == "e2e-test"
        assert loaded["status"] == "active"

    def test_start_project_validates_heartbeat_member(self, temp_hermes_home):
        """start_project returns error if heartbeat_member doesn't exist."""
        from project_planner import start_project

        result = start_project(
            project_name="bad-project",
            workdir="/tmp",
            heartbeat_member="nonexistent-worker",
        )
        assert "error" in result
        assert "not found" in result["error"]

    def test_stop_project_pauses_cron(self, temp_hermes_home, mock_worker):
        """stop_project removes cron and sets status to stopped."""
        from project_planner import start_project, stop_project, get_project

        with patch("project_planner._create_heartbeat_cron", return_value="cron-123"):
            start_project(
                project_name="stop-test",
                workdir="/tmp",
                heartbeat_member="test-leader",
            )

        with patch("project_planner._remove_heartbeat_cron") as mock_remove:
            result = stop_project("stop-test")

        assert result["status"] == "stopped"
        mock_remove.assert_called_once_with("cron-123")

        # Verify on disk
        proj = get_project("stop-test")
        assert proj["status"] == "stopped"

    def test_list_projects(self, temp_hermes_home, mock_worker):
        """list_projects returns all registered projects."""
        from project_planner import start_project, list_projects

        with patch("project_planner._create_heartbeat_cron", return_value="cron-1"):
            start_project("proj-a", "/tmp", goal="A", heartbeat_member="test-leader")
        with patch("project_planner._create_heartbeat_cron", return_value="cron-2"):
            start_project("proj-b", "/tmp", goal="B", heartbeat_member="test-leader")

        projects = list_projects()
        names = [p["name"] for p in projects]
        assert "proj-a" in names
        assert "proj-b" in names


# --------------------------------------------------------------------------- #
#  E2E Test 2: Heartbeat trigger path                                         #
# --------------------------------------------------------------------------- #

class TestHeartbeatPipeline:
    """Verify leader_loop.heartbeat spawns the agent and detects completion."""

    def test_heartbeat_project_not_found(self, temp_hermes_home):
        """heartbeat() returns error for unknown project."""
        from agora.leader_loop import heartbeat
        result = heartbeat(project="nonexistent")
        assert "error" in result
        assert "not found" in result["error"]

    def test_heartbeat_project_not_active(self, temp_hermes_home, mock_worker):
        """heartbeat() returns error for stopped project."""
        from agora.leader_loop import heartbeat
        from project_planner import start_project, stop_project

        with patch("project_planner._create_heartbeat_cron", return_value="cron-x"):
            start_project("inactive-proj", "/tmp", heartbeat_member="test-leader")
        stop_project("inactive-proj")

        result = heartbeat(project="inactive-proj")
        assert "error" in result
        assert "not active" in result["error"]

    def test_heartbeat_spawns_agent(self, temp_hermes_home, mock_worker):
        """heartbeat() spawns a subprocess and updates project status."""
        from agora.leader_loop import heartbeat
        from project_planner import start_project, get_project

        with patch("project_planner._create_heartbeat_cron", return_value="cron-h"):
            start_project("hb-test", "/tmp", goal="Test goal", heartbeat_member="test-leader")

        # Mock subprocess.Popen to simulate a successful spawn
        mock_proc = MagicMock()
        mock_proc.pid = 12345

        with patch("agora.leader_loop.subprocess.Popen", return_value=mock_proc) as mock_popen, \
             patch("agora.leader_loop.find_hermes_binary", return_value="/fake/hermes"):
            result = heartbeat(project="hb-test")

        assert result["status"] == "spawned"
        assert result["leader"] == "test-leader"
        assert result["project"] == "hb-test"
        assert result["pid"] == 12345

        # Verify Popen was called with the right profile
        cmd = mock_popen.call_args[0][0]
        assert "-p" in cmd
        assert "test-leader" in cmd
        assert "--yolo" in cmd
        assert "chat" in cmd

        # Verify project was updated with heartbeat info
        proj = get_project("hb-test")
        assert proj["last_heartbeat_at"] is not None
        assert proj["last_heartbeat_pid"] == 12345

    def test_check_project_complete_detects_marker(self, temp_hermes_home, mock_worker):
        """check_project_complete reads the log and detects PROJECT_COMPLETE."""
        from agora.leader_loop import check_project_complete, heartbeat
        from project_planner import start_project, get_project
        from agora.utils import get_registry_dir

        with patch("project_planner._create_heartbeat_cron", return_value="cron-c"):
            start_project("complete-test", "/tmp", heartbeat_member="test-leader")

        # Write a fake log with PROJECT_COMPLETE marker
        log_dir = get_registry_dir("projects")
        log_path = log_dir / "heartbeat_complete-test.log"
        log_path.write_text("Some output...\nPROJECT_COMPLETE\nGoal achieved.\n")

        result = check_project_complete("complete-test")
        assert result is True

        # Verify project status was updated to completed
        proj = get_project("complete-test")
        assert proj["status"] == "completed"
        assert proj.get("completed_at") is not None

    def test_check_project_complete_no_marker(self, temp_hermes_home, mock_worker):
        """check_project_complete returns False when log has no marker."""
        from agora.leader_loop import check_project_complete
        from project_planner import start_project
        from agora.utils import get_registry_dir

        with patch("project_planner._create_heartbeat_cron", return_value="cron-n"):
            start_project("incomplete-test", "/tmp", heartbeat_member="test-leader")

        log_dir = get_registry_dir("projects")
        log_path = log_dir / "heartbeat_incomplete-test.log"
        log_path.write_text("Working on tasks...\nStill running...\n")

        result = check_project_complete("incomplete-test")
        assert result is False


# --------------------------------------------------------------------------- #
#  E2E Test 3: Full discussion flow                                           #
# --------------------------------------------------------------------------- #

class TestDiscussionFlowE2E:
    """Verify the full event-driven discussion pipeline.

    Mocks spawn_chair_speak and spawn_agent_speak to return canned JSON,
    but exercises the real DiscussionDriver.run() flow including:
    motion creation → chair open → speaker speak → evaluate → vote →
    summarize → close motion → write memories.
    """

    @pytest.fixture()
    def setup_motion(self, temp_hermes_home):
        """Create a motion and return its ID."""
        from agora.storage import motions as db

        # Ensure DB is initialized
        conn = db._connect()
        conn.close()

        motion = db.create_motion(
            title="Use SQLite or PostgreSQL?",
            description="Decide on the database for the new feature.",
            participants=["alice", "bob"],
            chair="leader",
            max_steps=5,
        )
        return motion["id"]

    def test_full_discussion_with_vote(self, temp_hermes_home, setup_motion):
        """Full discussion: open → speak → evaluate(vote) → vote → summarize."""
        from agora.discussion.driver import DiscussionDriver
        from agora.storage import motions as db

        motion_id = setup_motion
        driver = DiscussionDriver(
            motion_id=motion_id,
            chair_profile="leader",
            participants=["alice", "bob"],
            workdir="/tmp",
            project_name="test-project",
            max_steps=5,
        )

        # Mock the agent spawns with predetermined responses
        chair_opening = json.dumps({
            "opening": "Let's discuss database choice.",
            "next_speaker": "alice",
            "guidance": "What are the pros of SQLite?",
        })
        alice_reply = "DISCUSSION_REPLY: I agree SQLite is simpler for this use case."
        chair_eval_vote = json.dumps({
            "action": "vote",
            "next_speaker": None,
            "guidance": None,
            "reason": "Both have spoken, time to vote.",
        })
        # Vote responses
        alice_vote = json.dumps({"vote": "adopt", "reason": "SQLite is good"})
        bob_vote = json.dumps({"vote": "adopt", "reason": "I agree"})
        # Summary
        chair_summary = json.dumps({
            "summary": "Team agrees on SQLite.",
            "action_items": [{"item": "Set up SQLite schema", "owner": "alice", "depends_on": []}],
            "confidence": 0.9,
            "decision": "adopted",
        })

        call_count = {"chair": 0, "agent": 0}

        def mock_chair_speak(profile, prompt, **kwargs):
            call_count["chair"] += 1
            if call_count["chair"] == 1:
                # Opening
                return {"reply": chair_opening, "error": None}
            elif call_count["chair"] == 2:
                # Evaluate after alice speaks → vote
                return {"reply": chair_eval_vote, "error": None}
            else:
                # Summary
                return {"reply": chair_summary, "error": None}

        def mock_agent_speak(profile_name, prompt, **kwargs):
            call_count["agent"] += 1
            if call_count["agent"] <= 1:
                # Alice's speak turn
                return {"reply": alice_reply, "session_id": "sess-1", "error": None}
            elif call_count["agent"] == 2:
                # Alice's vote
                return {"reply": alice_vote, "session_id": "sess-2", "error": None}
            else:
                # Bob's vote
                return {"reply": bob_vote, "session_id": "sess-3", "error": None}

        with patch("agora.discussion.driver.spawn_chair_speak", side_effect=mock_chair_speak), \
             patch("agora.discussion.driver.spawn_agent_speak", side_effect=mock_agent_speak), \
             patch("agora.discussion.driver.DiscussionDriver._create_kanban_tasks", return_value=[]):

            result = driver.run()

        # Verify the result
        assert result.motion_id == motion_id
        assert result.decision == "adopted"
        assert result.confidence == 0.9
        assert len(result.votes) == 2
        assert len(result.action_items) == 1

        # Verify motion was closed in DB
        motion = db.get_motion(motion_id)
        assert motion["status"] == "closed"
        assert motion["decision"] == "adopted"
        assert motion["state"] == "closed"

        # Verify messages were stored
        messages = db.get_messages(motion_id)
        assert len(messages) >= 3  # opening + speak + chair guidance + votes
        step_types = [m["step_type"] for m in messages]
        assert "opening" in step_types
        assert "speak" in step_types

        # Verify votes were stored
        votes = db.get_votes(motion_id)
        assert len(votes) == 2
        vote_roles = [v["role"] for v in votes]
        assert "alice" in vote_roles
        assert "bob" in vote_roles

    def test_discussion_with_close_action(self, temp_hermes_home, setup_motion):
        """Discussion where chair calls 'close' instead of 'vote'."""
        from agora.discussion.driver import DiscussionDriver
        from agora.storage import motions as db

        motion_id = setup_motion
        driver = DiscussionDriver(
            motion_id=motion_id,
            chair_profile="leader",
            participants=["alice", "bob"],
            workdir="/tmp",
            max_steps=5,
        )

        chair_opening = json.dumps({
            "opening": "Quick discussion on this.",
            "next_speaker": "alice",
            "guidance": "Your thoughts?",
        })
        alice_reply = "DISCUSSION_REPLY: I think we should proceed."
        chair_eval_close = json.dumps({
            "action": "close",
            "next_speaker": None,
            "guidance": None,
            "reason": "Enough said, closing.",
        })
        chair_summary = json.dumps({
            "summary": "Proceed with the plan.",
            "action_items": [],
            "confidence": 0.8,
            "decision": "adopted",
        })

        call_count = {"chair": 0, "agent": 0}

        def mock_chair_speak(profile, prompt, **kwargs):
            call_count["chair"] += 1
            if call_count["chair"] == 1:
                return {"reply": chair_opening, "error": None}
            elif call_count["chair"] == 2:
                return {"reply": chair_eval_close, "error": None}
            else:
                return {"reply": chair_summary, "error": None}

        def mock_agent_speak(profile_name, prompt, **kwargs):
            call_count["agent"] += 1
            return {"reply": alice_reply, "session_id": "sess-x", "error": None}

        with patch("agora.discussion.driver.spawn_chair_speak", side_effect=mock_chair_speak), \
             patch("agora.discussion.driver.spawn_agent_speak", side_effect=mock_agent_speak), \
             patch("agora.discussion.driver.DiscussionDriver._create_kanban_tasks", return_value=[]):

            result = driver.run()

        assert result.decision == "adopted"
        assert len(result.votes) == 0  # no vote was called

        motion = db.get_motion(motion_id)
        assert motion["status"] == "closed"
        assert motion["step_count"] >= 1

    def test_discussion_chair_failure_aborts(self, temp_hermes_home, setup_motion):
        """If chair fails to open, discussion aborts with error."""
        from agora.discussion.driver import DiscussionDriver
        from agora.storage import motions as db

        motion_id = setup_motion
        driver = DiscussionDriver(
            motion_id=motion_id,
            chair_profile="leader",
            participants=["alice"],
            max_steps=3,
        )

        with patch("agora.discussion.driver.spawn_chair_speak",
                    return_value={"reply": "", "error": "spawn failed"}):
            result = driver.run()

        assert result.decision == "error"
        motion = db.get_motion(motion_id)
        assert motion["status"] == "closed"
        assert motion["decision"] == "error"

    def test_discussion_writes_participant_memories(self, temp_hermes_home, mock_worker):
        """Discussion _write_participant_memories writes to MEMORY.md."""
        from agora.discussion.driver import DiscussionDriver
        from agora.storage import motions as db
        from agora.utils import get_global_root

        # Create motion
        motion = db.create_motion(
            title="Memory test",
            description="Test memory writing.",
            participants=["test-leader"],  # use the mock_worker's profile
            chair="test-leader",
            max_steps=3,
        )

        driver = DiscussionDriver(
            motion_id=motion["id"],
            chair_profile="test-leader",
            participants=["test-leader"],
            workdir="/tmp",
            max_steps=3,
        )

        # Run with minimal mocking — chair opens, speaker speaks, chair closes
        chair_opening = json.dumps({
            "opening": "Discussion start.",
            "next_speaker": "test-leader",
            "guidance": "Speak.",
        })
        speaker_reply = "DISCUSSION_REPLY: I agree."
        chair_close = json.dumps({
            "action": "close",
            "reason": "Done.",
        })
        chair_summary = json.dumps({
            "summary": "Agreed.",
            "action_items": [],
            "confidence": 0.9,
            "decision": "adopted",
        })

        call_count = {"chair": 0}

        def mock_chair(profile, prompt, **kwargs):
            call_count["chair"] += 1
            if call_count["chair"] == 1:
                return {"reply": chair_opening, "error": None}
            elif call_count["chair"] == 2:
                return {"reply": chair_close, "error": None}
            return {"reply": chair_summary, "error": None}

        with patch("agora.discussion.driver.spawn_chair_speak", side_effect=mock_chair), \
             patch("agora.discussion.driver.spawn_agent_speak",
                   return_value={"reply": speaker_reply, "session_id": "s1", "error": None}), \
             patch("agora.discussion.driver.DiscussionDriver._create_kanban_tasks", return_value=[]):

            result = driver.run()

        assert result.decision == "adopted"

        # Verify memory was written to the participant's MEMORY.md
        global_root = get_global_root()
        memory_path = global_root / "profiles" / "test-leader" / "memories" / "MEMORY.md"
        assert memory_path.exists(), f"Memory file not created at {memory_path}"
        content = memory_path.read_text()
        assert "Memory test" in content
        assert "adopted" in content


# --------------------------------------------------------------------------- #
#  E2E Test 4: Kanban task lifecycle hooks                                    #
# --------------------------------------------------------------------------- #

class TestKanbanHooksE2E:
    """Verify the kanban hook system fires correctly.

    The hooks (kanban_task_completed, kanban_task_claimed, kanban_task_blocked)
    are the glue between kanban events and the Agora pipeline. We test
    them with mocked kanban_db since we can't run the real kanban system
    in unit tests, but we exercise the real hook functions.
    """

    def test_task_blocked_creates_motion(self, temp_hermes_home, mock_worker):
        """kanban_task_blocked with 'design decision' reason creates a motion."""
        from hooks import _on_task_blocked
        from agora.storage import motions as db

        # Ensure DB initialized
        conn = db._connect()
        conn.close()

        # Mock kanban_db — task lookup returns a task with agora tenant
        mock_task = MagicMock()
        mock_task.tenant = "agora-block-test"
        mock_task.__dict__ = {"tenant": "agora-block-test"}

        # Create a fake project so the hook recognizes it as Agora-managed
        from project_planner import start_project
        with patch("project_planner._create_heartbeat_cron", return_value="cron-b"):
            start_project("block-test", "/tmp", heartbeat_member="test-leader")

        # Mock the kanban_db module
        mock_kanban_db = MagicMock()
        mock_conn = MagicMock()
        mock_kanban_db.connect.return_value = mock_conn
        mock_kanban_db.get_task.return_value = mock_task

        import sys
        original_module = sys.modules.get("hermes_cli")
        sys.modules["hermes_cli"] = MagicMock(kanban_db=mock_kanban_db)

        try:
            _on_task_blocked(
                task_id="task-123",
                reason="Blocked by design decision: need to pick a framework",
                board="agora-block-test",
                profile_name="test-leader",
            )
        finally:
            if original_module:
                sys.modules["hermes_cli"] = original_module
            else:
                del sys.modules["hermes_cli"]

        # Verify a motion was created
        motions_list = db.list_motions(status_filter="all", limit=10)
        assert len(motions_list) > 0
        # Find our motion
        block_motions = [m for m in motions_list if "design decision" in m.get("title", "").lower()
                         or "Unblock" in m.get("title", "")]
        assert len(block_motions) > 0
        assert block_motions[0]["source_task_id"] == "task-123"
        assert block_motions[0]["blocking"] is True or block_motions[0]["blocking"] == 1

    def test_task_blocked_no_motion_for_generic_reason(self, temp_hermes_home, mock_worker):
        """kanban_task_blocked with generic reason does NOT create a motion."""
        from hooks import _on_task_blocked
        from agora.storage import motions as db

        conn = db._connect()
        conn.close()

        from project_planner import start_project
        with patch("project_planner._create_heartbeat_cron", return_value="cron-g"):
            start_project("block-test-2", "/tmp", heartbeat_member="test-leader")

        mock_task = MagicMock()
        mock_task.tenant = "agora-block-test-2"
        mock_task.__dict__ = {"tenant": "agora-block-test-2"}

        mock_kanban_db = MagicMock()
        mock_conn = MagicMock()
        mock_kanban_db.connect.return_value = mock_conn
        mock_kanban_db.get_task.return_value = mock_task

        import sys
        original_module = sys.modules.get("hermes_cli")
        sys.modules["hermes_cli"] = MagicMock(kanban_db=mock_kanban_db)

        try:
            _on_task_blocked(
                task_id="task-456",
                reason="Waiting for API to be available",
                board="agora-block-test-2",
                profile_name="test-leader",
            )
        finally:
            if original_module:
                sys.modules["hermes_cli"] = original_module
            else:
                del sys.modules["hermes_cli"]

        # No motion should have been created for this task
        motions_list = db.list_motions(status_filter="all", limit=50)
        task_motions = [m for m in motions_list if m.get("source_task_id") == "task-456"]
        assert len(task_motions) == 0

    def test_task_completed_triggers_planner_hook(self, temp_hermes_home, mock_worker):
        """kanban_task_completed calls project_planner.on_task_completed."""
        from hooks import _on_task_completed
        from project_planner import start_project

        with patch("project_planner._create_heartbeat_cron", return_value="cron-tc"):
            start_project("complete-hook-test", "/tmp", heartbeat_member="test-leader")

        # Mock the planner hook to verify it gets called
        with patch("project_planner.on_task_completed") as mock_planner:
            _on_task_completed(
                task_id="task-done-1",
                board="agora-complete-hook-test",
                assignee="test-leader",
                profile_name="test-leader",
            )
            mock_planner.assert_called_once()


# --------------------------------------------------------------------------- #
#  E2E Test 5: Worker session isolation                                       #
# --------------------------------------------------------------------------- #

class TestWorkerSessionIsolation:
    """Verify per-project session isolation for workers."""

    def test_per_project_session(self, temp_hermes_home, mock_worker):
        """get_worker_session / update_worker_session isolate by project."""
        from agora.worker_manager import get_worker_session, update_worker_session

        # No session initially
        assert get_worker_session("test-leader", "project-a") is None

        # Set session for project-a
        update_worker_session("test-leader", "sess-a", "project-a")
        assert get_worker_session("test-leader", "project-a") == "sess-a"

        # project-b should still have no session
        assert get_worker_session("test-leader", "project-b") is None

        # Set session for project-b
        update_worker_session("test-leader", "sess-b", "project-b")
        assert get_worker_session("test-leader", "project-b") == "sess-b"
        assert get_worker_session("test-leader", "project-a") == "sess-a"

    def test_clear_session(self, temp_hermes_home, mock_worker):
        """Passing None clears the project-specific session."""
        from agora.worker_manager import get_worker_session, update_worker_session

        update_worker_session("test-leader", "sess-x", "project-c")
        assert get_worker_session("test-leader", "project-c") == "sess-x"

        update_worker_session("test-leader", None, "project-c")
        assert get_worker_session("test-leader", "project-c") is None
