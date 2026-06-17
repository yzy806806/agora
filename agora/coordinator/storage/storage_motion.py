"""Storage mixin: Motion + Message + Vote CRUD methods."""
from __future__ import annotations

from typing import Optional

from . import motions as _motions
from . import messages as _messages
from . import votes as _votes


class StorageMotionMixin:
    """Motion-related Storage methods (dialect-aware)."""

    async def create_motion(self, title: str, description: str,
                            rounds: int = 3,
                            voting_method: str = "simple_majority",
                            context: str = "") -> dict:
        async with self._connection() as db:
            return await _motions.create_motion(
                db, self.dialect, title, description, rounds,
                voting_method, context)

    async def get_motion(self, motion_id: str) -> Optional[dict]:
        async with self._connection() as db:
            return await _motions.get_motion(db, self.dialect, motion_id)

    async def list_motions(self, status: Optional[str] = None,
                           limit: int = 100, offset: int = 0) -> list[dict]:
        async with self._connection() as db:
            return await _motions.list_motions(
                db, self.dialect, status, limit, offset)

    async def update_motion_status(self, motion_id: str, status: str,
                                   decision: Optional[str] = None,
                                   rationale: Optional[str] = None,
                                   action_items: Optional[list[str]] = None) -> None:
        async with self._connection() as db:
            await _motions.update_motion_status(
                db, self.dialect, motion_id, status,
                decision, rationale, action_items)

    async def increment_round(self, motion_id: str) -> int:
        async with self._connection() as db:
            return await _motions.increment_round(db, self.dialect, motion_id)


class StorageMessageMixin:
    async def add_message(self, motion_id: str, agent_id: str,
                          round_num: int, stance: str, content: str,
                          evidence: list[dict] | None = None) -> int:
        async with self._connection() as db:
            return await _messages.add_message(
                db, self.dialect, motion_id, agent_id,
                round_num, stance, content, evidence)

    async def get_messages(self, motion_id: str,
                           round_num: Optional[int] = None,
                           agent_id: Optional[str] = None) -> list[dict]:
        async with self._connection() as db:
            return await _messages.get_messages(
                db, self.dialect, motion_id, round_num, agent_id)

    async def count_messages_by_round(self, motion_id: str,
                                      round_num: int) -> int:
        async with self._connection() as db:
            return await _messages.count_messages_by_round(
                db, self.dialect, motion_id, round_num)


class StorageVoteMixin:
    async def add_vote(self, motion_id: str, agent_id: str, vote: str,
                       confidence: float = 1.0,
                       reason: Optional[str] = None,
                       vote_type: str = "binary",
                       vote_data: Optional[str] = None) -> int:
        async with self._connection() as db:
            return await _votes.add_vote(
                db, self.dialect, motion_id, agent_id, vote,
                confidence, reason, vote_type, vote_data)

    async def get_votes(self, motion_id: str) -> list[dict]:
        async with self._connection() as db:
            return await _votes.get_votes(db, self.dialect, motion_id)

    async def has_voted(self, motion_id: str, agent_id: str) -> bool:
        async with self._connection() as db:
            return await _votes.has_voted(db, self.dialect, motion_id, agent_id)

    async def count_votes(self, motion_id: str) -> dict[str, int]:
        async with self._connection() as db:
            return await _votes.count_votes(db, self.dialect, motion_id)

    async def get_vote_summary(self, motion_id: str) -> dict:
        async with self._connection() as db:
            return await _votes.get_vote_summary(db, self.dialect, motion_id)

    async def get_active_motion_count(self) -> int:
        async with self._connection() as db:
            return await _votes.get_active_motion_count(db, self.dialect)

    async def get_participant_count(self) -> int:
        async with self._connection() as db:
            return await _votes.get_participant_count(db, self.dialect)
