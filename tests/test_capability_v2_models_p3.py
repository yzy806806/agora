"""Tests for Protocol v2 meta models + re-exports (Phase 14+.E.1) — part 3.

Covers: AgentMetadata, ProtocolVersion, models/__init__.py re-exports.
"""
import pytest

from agora.coordinator.capability_v2_meta import (
    AgentMetadata,
    ProtocolVersion,
)
from agora.coordinator.models import (
    AgentCapabilities,
    AgentMetadata as AgentMetadataRe,
    ProtocolVersion as ProtocolVersionRe,
    SkillDeclaration,
    SkillProficiency,
    StructuredError,
    TaskResult,
    TaskResultStatus,
)


# --- AgentMetadata ---

def test_agent_metadata_defaults():
    m = AgentMetadata()
    assert m.version == ""
    assert m.homepage is None
    assert m.description == ""


def test_agent_metadata_full():
    m = AgentMetadata(
        version="3.1.0",
        homepage="https://github.com/org/agent",
        description="Expert reviewer",
        docs_url="https://docs.example.com",
    )
    assert m.version == "3.1.0"
    assert m.docs_url is not None


# --- ProtocolVersion ---

def test_protocol_version_defaults():
    pv = ProtocolVersion()
    assert pv.protocol_version == "2.0"
    assert pv.server_version is None
    assert pv.session_id is None


def test_protocol_version_full():
    pv = ProtocolVersion(
        protocol_version="2.0",
        server_version="0.15.0",
        session_id="sess-abc",
    )
    assert pv.server_version == "0.15.0"


# --- Re-exports from models/__init__.py ---

def test_re_exports_are_same_class():
    assert AgentMetadata is AgentMetadataRe
    assert ProtocolVersion is ProtocolVersionRe


def test_re_export_skill_declaration():
    sd = SkillDeclaration(name="go", proficiency=SkillProficiency.ADVANCED)
    assert sd.proficiency_value == 4


def test_re_export_task_result():
    tr = TaskResult(task_id="t-1", status=TaskResultStatus.SUCCESS)
    assert tr.status == TaskResultStatus.SUCCESS


def test_re_export_structured_error():
    err = StructuredError(code="X", message="y")
    assert err.code == "X"
