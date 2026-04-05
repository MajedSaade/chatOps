"""
commands.py — Infrastructure query functions for K8s and AWS.

Each function performs an infrastructure query and returns a
formatted string result. Used by the gateway bot's slash commands.
"""

import logging
from datetime import datetime, timezone

from kubernetes import client as k8s_client, config as k8s_config
import boto3

from app.config import KUBE_NAMESPACE

logger = logging.getLogger("discord-chatops")


# ── Kubernetes helpers ───────────────────────────────────────────────

def _load_kube_config() -> None:
    """Load in-cluster config when running as a pod, else local kubeconfig."""
    try:
        k8s_config.load_incluster_config()
    except k8s_config.ConfigException:
        k8s_config.load_kube_config()


def get_cluster_health() -> str:
    """
    Gather pod statuses in the configured namespace and return
    a formatted summary string.
    """
    try:
        _load_kube_config()
        v1 = k8s_client.CoreV1Api()
        pods = v1.list_namespaced_pod(namespace=KUBE_NAMESPACE)

        lines: list[str] = [f"**Cluster Health — `{KUBE_NAMESPACE}`**\n"]
        for pod in pods.items:
            phase = pod.status.phase
            emoji = "🟢" if phase == "Running" else "🔴"
            lines.append(f"{emoji} `{pod.metadata.name}` — {phase}")

        if not pods.items:
            lines.append("_No pods found in this namespace._")

        return "\n".join(lines)
    except Exception as exc:
        logger.exception("cluster-health failed")
        return f"❌ Failed to fetch cluster health:\n```{exc}```"


def get_logs(pod_name: str) -> str:
    """
    Retrieve the last 50 log lines for a specific pod and return
    them as a formatted string.
    """
    try:
        _load_kube_config()
        v1 = k8s_client.CoreV1Api()
        log_text = v1.read_namespaced_pod_log(
            name=pod_name,
            namespace=KUBE_NAMESPACE,
            tail_lines=50,
        )
        return f"**Logs — `{pod_name}`**\n```\n{log_text or '(empty)'}```"
    except Exception as exc:
        logger.exception("logs command failed")
        return f"❌ Failed to fetch logs for `{pod_name}`:\n```{exc}```"


def get_aws_cost() -> str:
    """
    Query AWS Cost Explorer for the month-to-date unblended cost
    and return the result as a formatted string.
    """
    try:
        ce = boto3.client("ce")
        now = datetime.now(timezone.utc)
        start = now.strftime("%Y-%m-01")
        end = now.strftime("%Y-%m-%d")

        result = ce.get_cost_and_usage(
            TimePeriod={"Start": start, "End": end},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
        )

        amount = result["ResultsByTime"][0]["Total"]["UnblendedCost"]
        cost = float(amount["Amount"])
        unit = amount["Unit"]

        return (
            f"**AWS Cost (MTD)**\n"
            f"💰 **${cost:,.2f}** {unit}\n"
            f"_Period: {start} → {end}_"
        )
    except Exception as exc:
        logger.exception("aws-cost command failed")
        return f"❌ Failed to fetch AWS costs:\n```{exc}```"
