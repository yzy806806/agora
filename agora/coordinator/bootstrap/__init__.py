"""Bootstrap package — self-organizing development engine for Agora.

BootstrapEngine orchestrates the full pipeline:
  trigger → discussion → approval → task generation

All task operations go through Agora's own Task API,
not any external agent framework (Hermes, OpenCode, etc).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from .approval_flow import ApprovalFlow
from .discussion_driver import DiscussionConfig, DiscussionDriver, DiscussionResult
from .routes import init_bootstrap
from .schedule_checker import check_scheduled_triggers, update_schedule_run
from .task_generator import TaskGenerator
from .trigger_manager import TriggerManager, TriggerType

logger = logging.getLogger(__name__)


@dataclass
class BootstrapConfig:
    """Configuration for the BootstrapEngine."""
    db_path: str
    coordinator_url: str = "http://localhost:8765"


class BootstrapEngine:
    """Self-organizing development engine — coordinates all bootstrap modules.

    Pipeline: trigger → discussion → approval → task generation.
    All via Agora's own APIs. No dependency on any specific agent framework.
    """

    def __init__(self, config: BootstrapConfig) -> None:
        self.config = config
        self.trigger_mgr = TriggerManager(config.db_path)
        self.discussion_driver = DiscussionDriver(config.coordinator_url)
        self.task_generator = TaskGenerator(config.coordinator_url)
        self.approval_flow = ApprovalFlow(config.db_path)

    def init_routes(self) -> None:
        """Initialize route singletons. Call after engine creation."""
        init_bootstrap(
            self.trigger_mgr, self.approval_flow, self.config.db_path,
        )

    async def process_triggers(self) -> list[str]:
        """Process all pending triggers. Returns list of motion_ids."""
        triggers = await self.trigger_mgr.get_pending_triggers()
        motion_ids: list[str] = []
        for trigger in triggers:
            try:
                mid = await self._process_trigger(trigger)
                motion_ids.append(mid)
            except Exception as exc:
                logger.error("Trigger %s failed: %s", trigger.get("id"), exc)
                await self.trigger_mgr.mark_failed(str(trigger["id"]))
        return motion_ids

    async def _process_trigger(self, trigger: dict) -> str:
        """Process a single trigger: discuss → wait → submit approval."""
        config = DiscussionConfig(
            motion_title=trigger["topic"],
            motion_description=trigger.get("context", ""),
            participants=["architect", "developer", "reviewer"],
        )
        motion_id = await self.discussion_driver.start_dev_discussion(config)
        result = await self.discussion_driver.wait_for_result(motion_id)
        await self.approval_flow.submit_for_approval(
            motion_id=motion_id,
            decision=result.decision,
            rationale=result.rationale,
            action_items=result.recommended_actions,
        )
        await self.trigger_mgr.mark_processed(str(trigger["id"]))
        return motion_id

    async def process_approval(
        self, approval_id: str, approved: bool,
        approved_by: str = "user", feedback: Optional[str] = None,
    ) -> dict:
        """Process an approval decision and generate tasks if approved."""
        result = await self.approval_flow.handle_approval(
            approval_id, approved, approved_by, feedback,
        )
        if approved:
            approval = await self.approval_flow.get_approval(approval_id)
            if approval and approval.get("action_items"):
                items = json.loads(approval["action_items"])
                task_ids = await self.task_generator.generate_tasks(
                    {"action_items": items},
                )
                result["tasks_created"] = task_ids
        return result

    async def check_schedules(self) -> list[str]:
        """Check and fire due scheduled triggers. Returns trigger ids."""
        due = await check_scheduled_triggers(self.config.db_path)
        trigger_ids: list[str] = []
        for sched in due:
            topic = sched.get("topic_template", "Scheduled review")
            tid = await self.trigger_mgr.create_trigger(
                trigger_type=TriggerType.SCHEDULED,
                topic=topic,
                source=f"schedule:{sched['id']}",
                context=sched.get("cron_expression", ""),
            )
            trigger_ids.append(tid)
            await update_schedule_run(
                self.config.db_path,
                sched["id"],
                datetime.now(timezone.utc).isoformat(),
                None,
            )
        return trigger_ids
