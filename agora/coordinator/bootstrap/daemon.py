"""Bootstrap Daemon — self-driving development loop for Agora.

This is the built-in daemon that replaces the external auto_bootstrap.py
script. It runs as `agora daemon` and handles the full self-driving cycle:

  1. Check for new work (triggers, GitHub issues, scheduled reviews)
  2. Start discussions for pending triggers
  3. Wait for discussion results
  4. Submit for user approval (if auto_approve is off)
  5. Generate tasks from approved results
  6. Optionally: git commit + push, update docs

All configuration comes from the Settings API (Dashboard-manageable).
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiohttp

from . import BootstrapConfig, BootstrapEngine
from .trigger_manager import TriggerType
from .task_generator import TaskGenerator
from ..settings_manager import SettingsManager

logger = logging.getLogger(__name__)


class DaemonRunner:
    """Run the bootstrap daemon loop."""

    def __init__(
        self,
        db_path: str,
        coordinator_url: str = "http://localhost:8765",
        interval_minutes: int = 30,
        dry_run: bool = False,
        once: bool = False,
    ) -> None:
        self.db_path = db_path
        self.coordinator_url = coordinator_url.rstrip("/")
        self.interval = interval_minutes * 60
        self.dry_run = dry_run
        self.once = once
        self.engine = BootstrapEngine(BootstrapConfig(
            db_path=db_path,
            coordinator_url=coordinator_url,
        ))
        self.settings = SettingsManager()

    async def run(self) -> None:
        """Main daemon loop."""
        logger.info(
            "Agora daemon started (interval=%ds, dry_run=%s)",
            self.interval, self.dry_run,
        )
        while True:
            try:
                await self._tick()
            except Exception as exc:
                logger.error("Daemon tick failed: %s", exc, exc_info=True)
            if self.once:
                logger.info("Daemon --once mode: exiting after first tick")
                return
            logger.info("Next tick in %d seconds", self.interval)
            await asyncio.sleep(self.interval)

    async def _tick(self) -> None:
        """One iteration of the daemon loop."""
        now = datetime.now(timezone.utc).isoformat()
        logger.info("=== Daemon tick at %s ===", now)

        # 1. Check scheduled triggers
        trigger_ids = await self.engine.check_schedules()
        if trigger_ids:
            logger.info("Fired %d scheduled triggers", len(trigger_ids))

        # 2. Check GitHub issues (if enabled)
        if self.settings.get("bootstrap_github_sync"):
            await self._check_github_issues()

        # 3. Process pending triggers
        motion_ids = await self.engine.process_triggers()
        if motion_ids:
            logger.info("Started %d discussions", len(motion_ids))

        # 4. Check for pending approvals
        await self._process_pending_approvals()

        # 5. Check for completed tasks that need git commit
        if self.settings.get("git_auto_commit"):
            await self._auto_commit_completed_tasks()

    async def _check_github_issues(self) -> None:
        """Check GitHub for issues labeled 'needs-discussion'."""
        repo = self.settings.get("github_repo")
        if not repo:
            return
        token = self.settings.get("github_token")
        try:
            issues = await self._fetch_github_issues(repo, token)
            for issue in issues:
                title = issue.get("title", "")
                number = issue.get("number", "")
                url = issue.get("url", "")
                await self.engine.trigger_mgr.create_trigger(
                    trigger_type=TriggerType.GITHUB_ISSUE,
                    topic=f"GitHub #{number}: {title}",
                    source=url,
                    context=json.dumps(issue),
                    priority=5,
                )
                logger.info("Created trigger for GitHub issue #%s", number)
        except Exception as exc:
            logger.warning("GitHub issue check failed: %s", exc)

    async def _fetch_github_issues(
        self, repo: str, token: Optional[str] = None,
    ) -> list[dict]:
        """Fetch GitHub issues with 'needs-discussion' label."""
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        url = f"https://api.github.com/repos/{repo}/issues?labels=needs-discussion&state=open"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    return await resp.json()
                logger.warning("GitHub API returned %s", resp.status)
                return []

    async def _process_pending_approvals(self) -> None:
        """Auto-approve if configured, otherwise just log."""
        approvals = await self.engine.approval_flow.list_pending()
        if not approvals:
            return
        auto_approve = self.settings.get("bootstrap_auto_approve")
        for approval in approvals:
            if auto_approve:
                result = await self.engine.process_approval(
                    approval_id=str(approval["id"]),
                    approved=True,
                    approved_by="daemon",
                )
                logger.info("Auto-approved: %s", result)
            else:
                logger.info(
                    "Pending approval #%s (motion %s) — waiting for user",
                    approval["id"], approval.get("motion_id"),
                )

    async def _auto_commit_completed_tasks(self) -> None:
        """Git commit and push for completed tasks."""
        # This is a placeholder — actual implementation would:
        # 1. Query completed tasks from the Task API
        # 2. Stage changed files
        # 3. Commit with task title as message
        # 4. Push to remote
        logger.debug("Auto-commit check (not yet implemented)")


async def run_daemon(
    db_path: str,
    coordinator_url: str = "http://localhost:8765",
    interval_minutes: int = 30,
    dry_run: bool = False,
    once: bool = False,
) -> None:
    """Entry point for `agora daemon`."""
    runner = DaemonRunner(
        db_path=db_path,
        coordinator_url=coordinator_url,
        interval_minutes=interval_minutes,
        dry_run=dry_run,
        once=once,
    )
    await runner.run()
