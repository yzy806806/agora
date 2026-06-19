"""Tests for workspace MCP tools: get_workspace_file, put_workspace_file.

WorkspaceManager is imported lazily inside the tool functions,
so we patch at the source module level.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agora.coordinator.workspace.models import FileNode


def _make_file_node(**overrides) -> FileNode:
    """Create a FileNode with sensible defaults."""
    defaults = dict(
        project_id="proj", path="hello.txt",
        name="hello.txt", file_type="file", parent_path="/",
        size=13, content_type="text/plain",
        checksum_sha256="abc123", created_by="mcp",
        version=1,
    )
    defaults.update(overrides)
    return FileNode(**defaults)


class TestGetWorkspaceFile:
    @pytest.mark.asyncio
    async def test_file_not_found(self):
        with patch(
            "agora.coordinator.workspace.manager.WorkspaceManager"
        ) as MockWM:
            mock_inst = AsyncMock()
            mock_inst.read_file.return_value = (None, b"")
            MockWM.return_value = mock_inst

            from agora.coordinator.mcp.tools.workspace_tools import (
                get_workspace_file,
            )
            result = await get_workspace_file(
                project_id="proj", path="missing.txt",
            )
            assert "error" in result
            assert result["code"] == 404

    @pytest.mark.asyncio
    async def test_read_text_file(self):
        node = _make_file_node()
        with patch(
            "agora.coordinator.workspace.manager.WorkspaceManager"
        ) as MockWM:
            mock_inst = AsyncMock()
            mock_inst.read_file.return_value = (node, b"Hello, World!")
            MockWM.return_value = mock_inst

            from agora.coordinator.mcp.tools.workspace_tools import (
                get_workspace_file,
            )
            result = await get_workspace_file(
                project_id="proj", path="hello.txt",
            )
            assert result["content"] == "Hello, World!"
            assert result["size"] == 13


class TestPutWorkspaceFile:
    @pytest.mark.asyncio
    async def test_write_text_file(self):
        node = _make_file_node(size=12)
        with patch(
            "agora.coordinator.workspace.manager.WorkspaceManager"
        ) as MockWM:
            mock_inst = AsyncMock()
            mock_inst.write_file.return_value = node
            MockWM.return_value = mock_inst

            from agora.coordinator.mcp.tools.workspace_tools import (
                put_workspace_file,
            )
            result = await put_workspace_file(
                project_id="proj", path="new.txt",
                content="Test content",
            )
            assert result["path"] == "new.txt"
            assert result["size"] == 12

    @pytest.mark.asyncio
    async def test_content_too_large(self):
        from agora.coordinator.mcp.tools.workspace_tools import (
            put_workspace_file,
        )
        big = "x" * (1_048_577)
        result = await put_workspace_file(
            project_id="proj", path="big.txt", content=big,
        )
        assert "error" in result
        assert result["code"] == 413
