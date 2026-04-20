"""
commands.py — Infrastructure query and AI gateway command helpers.

Each function performs an operation and returns a formatted string
result. Used by the gateway bot's slash commands.
"""

import json
import logging
import os
from datetime import datetime, timezone

from kubernetes import client as k8s_client, config as k8s_config
import boto3
import aiohttp

from app.config import KUBE_NAMESPACE

logger = logging.getLogger("discord-chatops")

DEFAULT_AI_GATEWAY_URL = "http://127.0.0.1:8080/process-command"
GATEWAY_UNAVAILABLE_MESSAGE = "❌ AI gateway is unavailable right now. Please try again shortly."


class GatewayUnavailableError(RuntimeError):
    """Raised when the AI gateway cannot be reached."""


class GatewayResponseError(RuntimeError):
    """Raised when the AI gateway returns an invalid or error response."""


def _gateway_url() -> str:
    return os.getenv("AI_GATEWAY_URL", DEFAULT_AI_GATEWAY_URL).strip() or DEFAULT_AI_GATEWAY_URL


def _command_prefix(command_text: str) -> str:
    command = command_text.strip().split(maxsplit=1)[0] if command_text.strip() else "unknown"
    command = command.lstrip("/").lower()
    return command.split("/", maxsplit=1)[0] or "unknown"


def _extract_gateway_error(data: dict) -> str | None:
    for key in ("error", "message", "detail"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    errors = data.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, str) and first.strip():
            return first.strip()
        if isinstance(first, dict):
            for key in ("message", "detail", "error"):
                value = first.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

    return None


def _extract_gateway_text(data: dict) -> str | None:
    for key in ("text", "response", "result", "message"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _format_detect_results(data: dict) -> str | None:
    detections = data.get("detections")
    if not isinstance(detections, list):
        return None

    if not detections:
        return "✅ Detection completed. No objects were detected."

    lines = ["**Detection Results**"]
    for idx, det in enumerate(detections, start=1):
        if not isinstance(det, dict):
            lines.append(f"{idx}. {det}")
            continue

        label = det.get("label") or det.get("class") or "unknown"
        conf = det.get("confidence") or det.get("score")
        bbox = det.get("bbox") or det.get("box")

        entry = f"{idx}. {label}"
        if conf is not None:
            entry += f" (conf={conf})"
        if bbox is not None:
            entry += f" bbox={bbox}"
        lines.append(entry)

    annotated_path = data.get("annotated_image_path") or data.get("annotated_path")
    if isinstance(annotated_path, str) and annotated_path.strip():
        lines.append(f"Annotated image: {annotated_path.strip()}")

    return "\n".join(lines)


async def call_ai_gateway(
    user_id: str,
    command_text: str,
    image_url: str | None = None,
) -> dict:
    """Send a command payload to the AI gateway and return parsed JSON."""
    if not command_text.strip():
        raise GatewayResponseError("Command text cannot be empty.")

    gateway_url = _gateway_url()
    command_prefix = _command_prefix(command_text)
    payload = {
        "user_id": str(user_id),
        "command_text": command_text,
        "image_url": image_url,
    }

    timeout = aiohttp.ClientTimeout(total=int(os.getenv("AI_GATEWAY_TIMEOUT_SECONDS", "30")))
    logger.info("AI gateway request url=%s command_prefix=%s", gateway_url, command_prefix)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(gateway_url, json=payload) as response:
                logger.info(
                    "AI gateway response status=%s command_prefix=%s",
                    response.status,
                    command_prefix,
                )

                if response.status >= 400:
                    body = (await response.text()).strip()
                    concise_body = body.replace("\n", " ")[:300]
                    logger.warning(
                        "AI gateway non-200 status=%s command_prefix=%s body=%s",
                        response.status,
                        command_prefix,
                        concise_body,
                    )

                    user_error = f"Gateway returned HTTP {response.status}."
                    if body:
                        try:
                            data = json.loads(body)
                            if isinstance(data, dict):
                                extracted = _extract_gateway_error(data)
                                if extracted:
                                    user_error = extracted
                        except json.JSONDecodeError:
                            pass

                    raise GatewayResponseError(user_error)

                try:
                    data = await response.json(content_type=None)
                except (aiohttp.ContentTypeError, json.JSONDecodeError):
                    raise GatewayResponseError("Gateway returned invalid JSON.")

                if not isinstance(data, dict):
                    raise GatewayResponseError("Gateway response format is unsupported.")

                return data
    except (aiohttp.ClientConnectorError, aiohttp.ClientError, TimeoutError) as exc:
        logger.warning("AI gateway unavailable command_prefix=%s error=%s", command_prefix, exc)
        raise GatewayUnavailableError("AI gateway unavailable")


def format_gateway_success(data: dict) -> str:
    """Build a user-facing response from a successful gateway JSON payload."""
    detect_output = _format_detect_results(data)
    if detect_output:
        return detect_output

    text = _extract_gateway_text(data)
    if text:
        return text

    return f"✅ Gateway response:\n```json\n{json.dumps(data, indent=2)[:1500]}\n```"


async def run_gateway_command(user_id: str, command_text: str, image_url: str | None = None) -> str:
    """Execute a command through the AI gateway with clean user-facing failures."""
    try:
        data = await call_ai_gateway(user_id=user_id, command_text=command_text, image_url=image_url)
    except GatewayUnavailableError:
        return GATEWAY_UNAVAILABLE_MESSAGE
    except GatewayResponseError as exc:
        return f"❌ {exc}"

    error_text = _extract_gateway_error(data)
    if error_text and not _extract_gateway_text(data):
        return f"❌ {error_text}"

    return format_gateway_success(data)


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


async def ask_ollama(user_id: str, prompt: str) -> str:
    """Run /ask through the AI gateway."""
    if not prompt.strip():
        return "⚠️ Please provide a prompt for /ask."
    return await run_gateway_command(user_id=user_id, command_text=f"ask/{prompt.strip()}")


async def analyze_ollama(user_id: str, user_input: str) -> str:
    """Run /analyze through the AI gateway."""
    if not user_input.strip():
        return "⚠️ Please provide text/data for /analyze."
    return await run_gateway_command(user_id=user_id, command_text=f"analyze/{user_input.strip()}")


async def detect_yolo(user_id: str, image_url: str | None) -> str:
    """Run /detect through the AI gateway."""
    if not image_url:
        return "⚠️ Please provide an image URL for /detect."
    return await run_gateway_command(user_id=user_id, command_text="detect/image", image_url=image_url)
