"""Tests for Helm chart coordinator templates (deployment, hpa, service)."""
import json
import subprocess
from pathlib import Path

import yaml

CHART_DIR = Path(__file__).resolve().parents[1] / "deploy" / "helm" / "agora"


def _helm_template(extra_args: list[str] | None = None) -> dict[str, dict]:
    """Render chart with helm template, return {name: manifest}."""
    cmd = ["helm", "template", "test-release", str(CHART_DIR)]
    if extra_args:
        cmd.extend(extra_args)
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    docs: dict[str, dict] = {}
    for doc in yaml.safe_load_all(result.stdout):
        if doc is None:
            continue
        kind = doc.get("kind", "")
        name = doc.get("metadata", {}).get("name", "")
        docs[f"{kind}/{name}"] = doc
    return docs


def _find(docs: dict, kind: str, suffix: str) -> dict:
    """Find a manifest by kind and name suffix."""
    for key, val in docs.items():
        if key.startswith(f"{kind}/") and key.endswith(suffix):
            return val
    raise KeyError(f"No {kind}/*{suffix} found in {list(docs.keys())}")


class TestCoordinatorDeployment:
    """Validate coordinator-deployment.yaml."""

    def test_deployment_exists(self):
        docs = _helm_template()
        dep = _find(docs, "Deployment", "coordinator")
        assert dep["kind"] == "Deployment"

    def test_rolling_update_strategy(self):
        docs = _helm_template()
        dep = _find(docs, "Deployment", "coordinator")
        strat = dep["spec"]["strategy"]
        assert strat["type"] == "RollingUpdate"
        assert strat["rollingUpdate"]["maxSurge"] == 1
        assert strat["rollingUpdate"]["maxUnavailable"] == 0

    def test_termination_grace_period(self):
        docs = _helm_template()
        dep = _find(docs, "Deployment", "coordinator")
        assert dep["spec"]["template"]["spec"][
            "terminationGracePeriodSeconds"
        ] == 30

    def test_health_probes(self):
        docs = _helm_template()
        dep = _find(docs, "Deployment", "coordinator")
        container = dep["spec"]["template"]["spec"]["containers"][0]
        for probe_name in ("livenessProbe", "readinessProbe"):
            probe = container[probe_name]
            assert probe["httpGet"]["path"] == "/api/v1/health"
            assert probe["httpGet"]["port"] == "http"

    def test_init_container_migrate(self):
        docs = _helm_template()
        dep = _find(docs, "Deployment", "coordinator")
        inits = dep["spec"]["template"]["spec"]["initContainers"]
        assert len(inits) >= 1
        assert inits[0]["name"] == "migrate"
        assert "agora" in inits[0]["command"]
        assert "migrate" in inits[0]["command"]

    def test_env_from_secrets(self):
        docs = _helm_template()
        dep = _find(docs, "Deployment", "coordinator")
        container = dep["spec"]["template"]["spec"]["containers"][0]
        env_names = [e["name"] for e in container.get("env", [])]
        assert "AGORA_DATABASE_URL" in env_names
        assert "AGORA_REDIS_URL" in env_names
        assert "AGORA_JWT_SECRET" in env_names

    def test_workspace_volume_mount(self):
        docs = _helm_template()
        dep = _find(docs, "Deployment", "coordinator")
        container = dep["spec"]["template"]["spec"]["containers"][0]
        mounts = container.get("volumeMounts", [])
        assert any(m["name"] == "workspace" for m in mounts)

    def test_resources_from_coordinator_section(self):
        docs = _helm_template()
        dep = _find(docs, "Deployment", "coordinator")
        container = dep["spec"]["template"]["spec"]["containers"][0]
        res = container["resources"]
        assert res["requests"]["cpu"] == "250m"
        assert res["limits"]["cpu"] == "1"

    def test_replica_count(self):
        docs = _helm_template()
        dep = _find(docs, "Deployment", "coordinator")
        assert dep["spec"]["replicas"] == 2


class TestCoordinatorHPA:
    """Validate coordinator-hpa.yaml."""

    def test_hpa_exists_when_enabled(self):
        docs = _helm_template()
        hpa = _find(docs, "HorizontalPodAutoscaler", "coordinator")
        assert hpa["kind"] == "HorizontalPodAutoscaler"

    def test_hpa_min_max_replicas(self):
        docs = _helm_template()
        hpa = _find(docs, "HorizontalPodAutoscaler", "coordinator")
        assert hpa["spec"]["minReplicas"] == 2
        assert hpa["spec"]["maxReplicas"] == 10

    def test_hpa_cpu_target(self):
        docs = _helm_template()
        hpa = _find(docs, "HorizontalPodAutoscaler", "coordinator")
        metrics = hpa["spec"]["metrics"]
        cpu_metric = metrics[0]
        assert cpu_metric["type"] == "Resource"
        assert cpu_metric["resource"]["name"] == "cpu"
        assert cpu_metric["resource"]["target"][
            "averageUtilization"
        ] == 70

    def test_hpa_absent_when_disabled(self):
        docs = _helm_template(
            ["--set", "coordinator.autoscaling.enabled=false"]
        )
        hpa_keys = [k for k in docs if "HorizontalPodAutoscaler" in k]
        assert len(hpa_keys) == 0


class TestCoordinatorService:
    """Validate coordinator-service.yaml."""

    def test_service_exists(self):
        docs = _helm_template()
        svc = _find(docs, "Service", "coordinator")
        assert svc["kind"] == "Service"

    def test_service_cluster_ip(self):
        docs = _helm_template()
        svc = _find(docs, "Service", "coordinator")
        assert svc["spec"]["type"] == "ClusterIP"

    def test_service_port(self):
        docs = _helm_template()
        svc = _find(docs, "Service", "coordinator")
        ports = svc["spec"]["ports"]
        assert any(p["port"] == 8000 for p in ports)

    def test_session_affinity(self):
        docs = _helm_template()
        svc = _find(docs, "Service", "coordinator")
        assert svc["spec"]["sessionAffinity"] == "ClientIP"

    def test_selector_matches_deployment(self):
        docs = _helm_template()
        svc = _find(docs, "Service", "coordinator")
        dep = _find(docs, "Deployment", "coordinator")
        svc_sel = svc["spec"]["selector"]
        pod_labels = dep["spec"]["template"]["metadata"]["labels"]
        for k, v in svc_sel.items():
            assert pod_labels.get(k) == v
