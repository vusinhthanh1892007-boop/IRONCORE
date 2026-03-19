"""Phase 12 — Kubernetes Helm Charts — Test Suite.

Tests validate:
1. Static YAML correctness of Chart.yaml, values.yaml, values-prod.yaml
2. Template file structure (Go template syntax checks)
3. helm lint / helm template (skipped if helm CLI not installed)
4. Rendered output checks via `helm template --set ...` (helm required)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

# ── Project root resolution ────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).parent.parent
_CHARTS_DIR = _PROJECT_ROOT / "charts" / "ironcore"
_TEMPLATES_DIR = _CHARTS_DIR / "templates"

# ── Helm availability check ────────────────────────────────────────────────
HAS_HELM = shutil.which("helm") is not None
requires_helm = pytest.mark.skipif(not HAS_HELM, reason="helm CLI not found in PATH")


def _helm(*args: str) -> subprocess.CompletedProcess:
    """Run helm with the ironcore chart directory and return CompletedProcess."""
    return subprocess.run(
        ["helm", *args],
        capture_output=True,
        text=True,
        cwd=str(_PROJECT_ROOT),
    )


def _helm_template(*set_args: str) -> str:
    """Run `helm template ironcore charts/ironcore --set ...` and return stdout."""
    cmd = ["helm", "template", "ironcore", "charts/ironcore"]
    for s in set_args:
        cmd.extend(["--set", s])
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(_PROJECT_ROOT))
    assert result.returncode == 0, f"helm template failed:\n{result.stderr}"
    return result.stdout


# ══════════════════════════════════════════════════════════════════════════════
#  TestChartStructure — Chart directory exists and expected files are present
# ══════════════════════════════════════════════════════════════════════════════

class TestChartStructure:
    def test_chart_dir_exists(self) -> None:
        assert _CHARTS_DIR.is_dir(), f"charts/ironcore/ directory missing at {_CHARTS_DIR}"

    def test_chart_yaml_exists(self) -> None:
        assert (_CHARTS_DIR / "Chart.yaml").is_file()

    def test_values_yaml_exists(self) -> None:
        assert (_CHARTS_DIR / "values.yaml").is_file()

    def test_values_prod_yaml_exists(self) -> None:
        assert (_CHARTS_DIR / "values-prod.yaml").is_file()

    def test_templates_dir_exists(self) -> None:
        assert _TEMPLATES_DIR.is_dir()

    @pytest.mark.parametrize("template", [
        "_helpers.tpl",
        "deployment.yaml",
        "worker-deployment.yaml",
        "service.yaml",
        "hpa.yaml",
        "keda-scaledobject.yaml",
        "configmap.yaml",
        "serviceaccount.yaml",
        "rbac.yaml",
        "ingress.yaml",
        "networkpolicy.yaml",
        "externalsecret.yaml",
    ])
    def test_template_file_exists(self, template: str) -> None:
        p = _TEMPLATES_DIR / template
        assert p.is_file(), f"Template missing: templates/{template}"


# ══════════════════════════════════════════════════════════════════════════════
#  TestChartYaml
# ══════════════════════════════════════════════════════════════════════════════

class TestChartYaml:
    @pytest.fixture(scope="class")
    def chart(self) -> dict:
        return yaml.safe_load((_CHARTS_DIR / "Chart.yaml").read_text())

    def test_api_version_v2(self, chart: dict) -> None:
        assert chart["apiVersion"] == "v2"

    def test_name(self, chart: dict) -> None:
        assert chart["name"] == "ironcore"

    def test_type_application(self, chart: dict) -> None:
        assert chart["type"] == "application"

    def test_version_present(self, chart: dict) -> None:
        assert "version" in chart
        assert chart["version"]

    def test_app_version_present(self, chart: dict) -> None:
        assert "appVersion" in chart

    def test_description_present(self, chart: dict) -> None:
        assert "description" in chart
        assert len(chart["description"]) > 10

    def test_maintainers_present(self, chart: dict) -> None:
        assert "maintainers" in chart
        assert isinstance(chart["maintainers"], list)
        assert len(chart["maintainers"]) >= 1

    def test_redis_dependency(self, chart: dict) -> None:
        deps = chart.get("dependencies", [])
        names = [d["name"] for d in deps]
        assert "redis" in names

    def test_redis_dependency_has_condition(self, chart: dict) -> None:
        deps = {d["name"]: d for d in chart.get("dependencies", [])}
        assert "condition" in deps["redis"]
        assert deps["redis"]["condition"] == "redis.enabled"


# ══════════════════════════════════════════════════════════════════════════════
#  TestValuesYaml
# ══════════════════════════════════════════════════════════════════════════════

class TestValuesYaml:
    @pytest.fixture(scope="class")
    def values(self) -> dict:
        return yaml.safe_load((_CHARTS_DIR / "values.yaml").read_text())

    def test_replica_count_is_int(self, values: dict) -> None:
        assert isinstance(values["replicaCount"], int)

    def test_autoscaling_section_present(self, values: dict) -> None:
        assert "autoscaling" in values
        assert "maxReplicas" in values["autoscaling"]
        assert values["autoscaling"]["maxReplicas"] == 10000

    def test_keda_section(self, values: dict) -> None:
        assert "keda" in values
        keda = values["keda"]
        assert keda["minReplicaCount"] == 0     # scale to zero
        assert keda["maxReplicaCount"] == 10000

    def test_edition_section(self, values: dict) -> None:
        assert values["edition"]["value"] == "enterprise"

    def test_airgap_section(self, values: dict) -> None:
        assert "airgap" in values
        assert "vllmBaseUrl" in values["airgap"]

    def test_networkpolicy_section(self, values: dict) -> None:
        assert "networkPolicy" in values

    def test_external_secrets_section(self, values: dict) -> None:
        assert "externalSecrets" in values
        es = values["externalSecrets"]
        assert "secretStoreRef" in es

    def test_worker_section(self, values: dict) -> None:
        assert "worker" in values
        assert "batchMode" in values["worker"]
        assert "maxIterations" in values["worker"]

    def test_siem_section(self, values: dict) -> None:
        assert "siem" in values
        assert "splunkHecToken" in values["siem"]

    def test_sso_section(self, values: dict) -> None:
        assert "sso" in values
        assert "provider" in values["sso"]

    def test_ingress_section(self, values: dict) -> None:
        assert "ingress" in values
        assert "hosts" in values["ingress"]
        assert values["ingress"]["hosts"][0]["host"] == "ironcore.bank.internal"

    def test_resources_section(self, values: dict) -> None:
        assert "resources" in values
        assert "requests" in values["resources"]
        assert "limits" in values["resources"]

    def test_security_context_drops_all_capabilities(self, values: dict) -> None:
        sc = values.get("securityContext", {})
        caps = sc.get("capabilities", {}).get("drop", [])
        assert "ALL" in caps

    def test_service_section(self, values: dict) -> None:
        assert values["service"]["port"] == 8000
        assert values["service"]["type"] == "ClusterIP"


# ══════════════════════════════════════════════════════════════════════════════
#  TestValuesProdYaml
# ══════════════════════════════════════════════════════════════════════════════

class TestValuesProdYaml:
    @pytest.fixture(scope="class")
    def prod(self) -> dict:
        return yaml.safe_load((_CHARTS_DIR / "values-prod.yaml").read_text())

    def test_airgap_enabled_in_prod(self, prod: dict) -> None:
        assert prod["airgap"]["enabled"] is True

    def test_networkpolicy_block_egress_in_prod(self, prod: dict) -> None:
        assert prod["networkPolicy"]["blockEgress"] is True

    def test_external_secrets_enabled_in_prod(self, prod: dict) -> None:
        assert prod["externalSecrets"]["enabled"] is True

    def test_siem_enabled_in_prod(self, prod: dict) -> None:
        assert prod["siem"]["enabled"] is True

    def test_replica_count_at_least_3_in_prod(self, prod: dict) -> None:
        assert prod["replicaCount"] >= 3

    def test_edition_enterprise_in_prod(self, prod: dict) -> None:
        assert prod["edition"]["value"] == "enterprise"


# ══════════════════════════════════════════════════════════════════════════════
#  TestTemplateContent — Static string checks on Go template files
# ══════════════════════════════════════════════════════════════════════════════

class TestTemplateContent:
    def _read(self, filename: str) -> str:
        return (_TEMPLATES_DIR / filename).read_text()

    def test_helpers_defines_fullname(self) -> None:
        content = self._read("_helpers.tpl")
        assert 'define "ironcore.fullname"' in content

    def test_helpers_defines_selector_labels(self) -> None:
        content = self._read("_helpers.tpl")
        assert 'define "ironcore.selectorLabels"' in content

    def test_helpers_defines_service_account_name(self) -> None:
        content = self._read("_helpers.tpl")
        assert 'define "ironcore.serviceAccountName"' in content

    def test_deployment_uses_edition_env(self) -> None:
        content = self._read("deployment.yaml")
        assert "IRONCORE_EDITION" in content
        assert ".Values.edition.value" in content

    def test_deployment_uses_airgap_condition(self) -> None:
        content = self._read("deployment.yaml")
        assert ".Values.airgap.enabled" in content
        assert "IRONCORE_AIRGAP_ENABLED" in content

    def test_deployment_has_liveness_probe(self) -> None:
        content = self._read("deployment.yaml")
        assert "livenessProbe" in content

    def test_deployment_has_readiness_probe(self) -> None:
        content = self._read("deployment.yaml")
        assert "readinessProbe" in content

    def test_deployment_uses_security_context(self) -> None:
        content = self._read("deployment.yaml")
        # securityContext is rendered via toYaml from values.yaml
        assert "securityContext" in content
        assert ".Values.securityContext" in content

    def test_hpa_uses_autoscaling_values(self) -> None:
        content = self._read("hpa.yaml")
        assert ".Values.autoscaling.enabled" in content
        assert ".Values.autoscaling.maxReplicas" in content

    def test_hpa_max_replicas_value(self) -> None:
        content = self._read("hpa.yaml")
        # The values.yaml default is 10000
        assert "maxReplicas" in content

    def test_keda_scaledobject_conditional(self) -> None:
        content = self._read("keda-scaledobject.yaml")
        assert ".Values.keda.enabled" in content
        assert "keda.sh/v1alpha1" in content
        assert "ScaledObject" in content

    def test_keda_min_replica_zero_value(self) -> None:
        content = self._read("keda-scaledobject.yaml")
        assert ".Values.keda.minReplicaCount" in content

    def test_keda_redis_trigger(self) -> None:
        content = self._read("keda-scaledobject.yaml")
        assert "type: redis" in content
        assert ".Values.keda.redisQueueName" in content

    def test_networkpolicy_conditional(self) -> None:
        content = self._read("networkpolicy.yaml")
        assert ".Values.networkPolicy.enabled" in content
        assert ".Values.networkPolicy.blockEgress" in content

    def test_networkpolicy_blocks_egress(self) -> None:
        content = self._read("networkpolicy.yaml")
        assert "policyTypes" in content
        assert "Egress" in content

    def test_networkpolicy_allows_dns(self) -> None:
        content = self._read("networkpolicy.yaml")
        assert "port: 53" in content

    def test_externalsecret_conditional(self) -> None:
        content = self._read("externalsecret.yaml")
        assert ".Values.externalSecrets.enabled" in content
        assert "external-secrets.io/v1beta1" in content
        assert "ExternalSecret" in content

    def test_externalsecret_uses_vault_mount_path(self) -> None:
        content = self._read("externalsecret.yaml")
        assert ".Values.externalSecrets.vaultMountPath" in content

    def test_externalsecret_has_siem_section(self) -> None:
        content = self._read("externalsecret.yaml")
        assert "splunk-hec-token" in content
        assert "datadog-api-key" in content

    def test_ingress_conditional(self) -> None:
        content = self._read("ingress.yaml")
        assert ".Values.ingress.enabled" in content
        assert "networking.k8s.io/v1" in content

    def test_worker_deployment_conditional(self) -> None:
        content = self._read("worker-deployment.yaml")
        assert ".Values.worker.enabled" in content
        assert "deployment.worker" in content

    def test_worker_deployment_batch_mode_env(self) -> None:
        content = self._read("worker-deployment.yaml")
        assert "IRONCORE_WORKER_BATCH_MODE" in content
        assert ".Values.worker.batchMode" in content

    def test_configmap_has_edition(self) -> None:
        content = self._read("configmap.yaml")
        assert "IRONCORE_EDITION" in content

    def test_rbac_creates_role_and_binding(self) -> None:
        content = self._read("rbac.yaml")
        assert "kind: Role" in content
        assert "kind: RoleBinding" in content
        assert ".Values.rbac.create" in content

    def test_serviceaccount_conditional(self) -> None:
        content = self._read("serviceaccount.yaml")
        assert ".Values.serviceAccount.create" in content
        assert "automountServiceAccountToken: false" in content


# ══════════════════════════════════════════════════════════════════════════════
#  TestHelmLint — Requires helm CLI
# ══════════════════════════════════════════════════════════════════════════════

class TestHelmLint:
    @requires_helm
    def test_helm_lint_passes(self) -> None:
        result = _helm("lint", "charts/ironcore")
        assert result.returncode == 0, f"helm lint failed:\n{result.stderr}\n{result.stdout}"

    @requires_helm
    def test_helm_lint_no_errors(self) -> None:
        result = _helm("lint", "charts/ironcore")
        assert "[ERROR]" not in result.stdout, f"helm lint reported errors:\n{result.stdout}"


# ══════════════════════════════════════════════════════════════════════════════
#  TestHelmTemplate — Requires helm CLI
# ══════════════════════════════════════════════════════════════════════════════

class TestHelmTemplate:
    @requires_helm
    def test_default_template_is_valid_yaml(self) -> None:
        output = _helm_template()
        # helm template produces multi-doc YAML (--- separated)
        docs = list(yaml.safe_load_all(output))
        # Filter None (empty docs from ---)
        docs = [d for d in docs if d is not None]
        assert len(docs) > 0, "helm template produced no YAML documents"

    @requires_helm
    def test_default_renders_deployment(self) -> None:
        output = _helm_template()
        docs = [d for d in yaml.safe_load_all(output) if d]
        kinds = [d.get("kind") for d in docs]
        assert "Deployment" in kinds

    @requires_helm
    def test_default_renders_service(self) -> None:
        output = _helm_template()
        docs = [d for d in yaml.safe_load_all(output) if d]
        kinds = [d.get("kind") for d in docs]
        assert "Service" in kinds

    @requires_helm
    def test_default_renders_hpa_when_enabled(self) -> None:
        output = _helm_template("autoscaling.enabled=true")
        docs = [d for d in yaml.safe_load_all(output) if d]
        kinds = [d.get("kind") for d in docs]
        assert "HorizontalPodAutoscaler" in kinds

    @requires_helm
    def test_networkpolicy_rendered_when_block_egress(self) -> None:
        output = _helm_template(
            "networkPolicy.enabled=true",
            "networkPolicy.blockEgress=true",
        )
        docs = [d for d in yaml.safe_load_all(output) if d]
        kinds = [d.get("kind") for d in docs]
        assert "NetworkPolicy" in kinds

    @requires_helm
    def test_networkpolicy_not_rendered_by_default(self) -> None:
        output = _helm_template()
        docs = [d for d in yaml.safe_load_all(output) if d]
        kinds = [d.get("kind") for d in docs]
        assert "NetworkPolicy" not in kinds

    @requires_helm
    def test_keda_scaledobject_rendered_when_enabled(self) -> None:
        output = _helm_template(
            "keda.enabled=true",
            "keda.redisAddress=redis:6379",
        )
        docs = [d for d in yaml.safe_load_all(output) if d]
        kinds = [d.get("kind") for d in docs]
        assert "ScaledObject" in kinds

    @requires_helm
    def test_keda_scaledobject_has_correct_min_replicas(self) -> None:
        output = _helm_template(
            "keda.enabled=true",
            "keda.minReplicaCount=0",
            "keda.maxReplicaCount=10000",
            "keda.redisAddress=redis:6379",
        )
        docs = [d for d in yaml.safe_load_all(output) if d]
        scaler = next((d for d in docs if d and d.get("kind") == "ScaledObject"), None)
        assert scaler is not None
        assert scaler["spec"]["minReplicaCount"] == 0
        assert scaler["spec"]["maxReplicaCount"] == 10000

    @requires_helm
    def test_externalsecrets_rendered_when_enabled(self) -> None:
        output = _helm_template(
            "externalSecrets.enabled=true",
        )
        docs = [d for d in yaml.safe_load_all(output) if d]
        kinds = [d.get("kind") for d in docs]
        assert "ExternalSecret" in kinds

    @requires_helm
    def test_deployment_contains_edition_env(self) -> None:
        output = _helm_template("edition.value=enterprise")
        docs = [d for d in yaml.safe_load_all(output) if d]
        deployments = [d for d in docs if d and d.get("kind") == "Deployment"
                       and d.get("metadata", {}).get("name", "").endswith("ironcore")]
        # Find the API deployment (not worker)
        api_dep = next(
            (d for d in deployments if "worker" not in d.get("metadata", {}).get("name", "")),
            None,
        )
        assert api_dep is not None
        envs = api_dep["spec"]["template"]["spec"]["containers"][0]["env"]
        edition_env = next((e for e in envs if e["name"] == "IRONCORE_EDITION"), None)
        assert edition_env is not None
        assert edition_env["value"] == "enterprise"

    @requires_helm
    def test_worker_deployment_rendered_when_enabled(self) -> None:
        output = _helm_template("worker.enabled=true")
        docs = [d for d in yaml.safe_load_all(output) if d]
        kinds_names = [(d.get("kind"), d.get("metadata", {}).get("name", ""))
                       for d in docs if d]
        assert any(kind == "Deployment" and "worker" in name
                   for kind, name in kinds_names)

    @requires_helm
    def test_ingress_rendered_by_default(self) -> None:
        output = _helm_template()
        docs = [d for d in yaml.safe_load_all(output) if d]
        kinds = [d.get("kind") for d in docs]
        assert "Ingress" in kinds

    @requires_helm
    def test_configmap_rendered(self) -> None:
        output = _helm_template()
        docs = [d for d in yaml.safe_load_all(output) if d]
        kinds = [d.get("kind") for d in docs]
        assert "ConfigMap" in kinds

    @requires_helm
    def test_rbac_rendered_by_default(self) -> None:
        output = _helm_template()
        docs = [d for d in yaml.safe_load_all(output) if d]
        kinds = [d.get("kind") for d in docs]
        assert "Role" in kinds
        assert "RoleBinding" in kinds

    @requires_helm
    def test_prod_values_render_without_error(self) -> None:
        result = subprocess.run(
            ["helm", "template", "ironcore", "charts/ironcore",
             "-f", "charts/ironcore/values-prod.yaml"],
            capture_output=True, text=True, cwd=str(_PROJECT_ROOT),
        )
        assert result.returncode == 0, f"prod values render failed:\n{result.stderr}"


# ══════════════════════════════════════════════════════════════════════════════
#  TestMakefile
# ══════════════════════════════════════════════════════════════════════════════

class TestMakefile:
    @pytest.fixture(scope="class")
    def makefile(self) -> str:
        return (_PROJECT_ROOT / "Makefile").read_text()

    def test_helm_lint_target_present(self, makefile: str) -> None:
        assert "helm-lint:" in makefile

    def test_helm_template_target_present(self, makefile: str) -> None:
        assert "helm-template:" in makefile

    def test_helm_install_dev_target_present(self, makefile: str) -> None:
        assert "helm-install-dev:" in makefile

    def test_helm_install_prod_target_present(self, makefile: str) -> None:
        assert "helm-install-prod:" in makefile

    def test_helm_batch_10k_target_present(self, makefile: str) -> None:
        assert "helm-batch-10k:" in makefile

    def test_batch_10k_sets_keda_enabled(self, makefile: str) -> None:
        assert "keda.enabled=true" in makefile

    def test_batch_10k_max_10000(self, makefile: str) -> None:
        assert "10000" in makefile
