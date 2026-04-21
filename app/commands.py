"""
commands.py — Infrastructure query and AI gateway command helpers.

Each function performs an operation and returns a formatted string
result. Used by the gateway bot's slash commands.
"""

import json
import logging
import os
import random
import asyncio
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import uuid4

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
    raw = os.getenv("AI_GATEWAY_URL", "").strip() or os.getenv("AI_GATEWAY_BASE_URL", "").strip()
    if not raw:
        return DEFAULT_AI_GATEWAY_URL

    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        logger.warning("gateway.config.invalid_url raw=%s fallback=%s", raw, DEFAULT_AI_GATEWAY_URL)
        return DEFAULT_AI_GATEWAY_URL

    if parsed.path in ("", "/"):
        normalized = raw.rstrip("/") + "/process-command"
        logger.info("gateway.config.normalized_path from=%s to=%s", raw, normalized)
        raw = normalized
        parsed = urlparse(raw)

    if os.path.exists("/.dockerenv") and parsed.hostname in {"127.0.0.1", "localhost"}:
        host_rewritten = raw.replace(parsed.hostname, "host.docker.internal", 1)
        logger.warning(
            "gateway.config.rewrite_loopback_in_container from=%s to=%s",
            raw,
            host_rewritten,
        )
        return host_rewritten

    return raw


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


def _response_snippet(body: str, limit: int = 300) -> str:
    return body.replace("\n", " ").strip()[:limit]


def _map_gateway_error_for_user(status: int, detail: str | None) -> str:
    if status == 400:
        return detail or "Invalid request sent to AI gateway."
    if status == 404:
        return "AI gateway endpoint was not found."
    if status == 408:
        return "AI gateway timed out while processing your command."
    if status == 413:
        return "Your command is too large for the AI gateway."
    if status == 422:
        return detail or "Your command format is invalid. Use ask/..., analyze/..., or detect/..."
    if status == 429:
        return "AI gateway is rate-limited right now. Please retry shortly."
    if status >= 500:
        return "AI gateway failed while processing your command."
    return detail or f"Gateway returned HTTP {status}."


def _is_likely_transient(exc: Exception) -> bool:
    return isinstance(exc, (aiohttp.ClientConnectorError, aiohttp.ClientOSError, aiohttp.ServerTimeoutError, TimeoutError))


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
    request_id: str | None = None,
    discord_channel_id: str | None = None,
    source: str = "discord",
) -> dict:
    """Send a command payload to the AI gateway and return parsed JSON."""
    if not command_text.strip():
        raise GatewayResponseError("Command text cannot be empty.")

    gateway_url = _gateway_url()
    trace_id = request_id or str(uuid4())
    retries = max(0, int(os.getenv("AI_GATEWAY_RETRY_ATTEMPTS", "1")))
    backoff_seconds = max(0.0, float(os.getenv("AI_GATEWAY_RETRY_BACKOFF_SECONDS", "0.35")))
    command_prefix = _command_prefix(command_text)
    payload = {
        "user_id": str(user_id),
        "command_text": str(command_text),
    }
    if image_url:
        payload["image_url"] = str(image_url)

    timeout = aiohttp.ClientTimeout(total=int(os.getenv("AI_GATEWAY_TIMEOUT_SECONDS", "30")))
    headers = {
        "Accept": "application/json",
        "X-Request-ID": trace_id,
    }

    for attempt in range(retries + 1):
        logger.info(
            "gateway.request request_id=%s source=%s discord_user_id=%s discord_channel_id=%s command_type=%s url=%s method=POST timeout_s=%s attempt=%s",
            trace_id,
            source,
            str(user_id),
            discord_channel_id or "unknown",
            command_prefix,
            gateway_url,
            timeout.total,
            attempt + 1,
        )

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(gateway_url, json=payload, headers=headers) as response:
                    body = (await response.text()).strip()
                    snippet = _response_snippet(body)
                    logger.info(
                        "gateway.response request_id=%s status_code=%s command_type=%s body_snippet=%s",
                        trace_id,
                        response.status,
                        command_prefix,
                        snippet,
                    )

                    if response.status >= 400:
                        detail = None
                        if body:
                            try:
                                data = json.loads(body)
                                if isinstance(data, dict):
                                    detail = _extract_gateway_error(data)
                            except json.JSONDecodeError:
                                detail = None

                        mapped_error = _map_gateway_error_for_user(response.status, detail)
                        logger.warning(
                            "gateway.non_2xx request_id=%s status_code=%s command_type=%s url=%s mapped_error=%s body_snippet=%s",
                            trace_id,
                            response.status,
                            command_prefix,
                            gateway_url,
                            mapped_error,
                            snippet,
                        )
                        raise GatewayResponseError(mapped_error)

                    try:
                        data = json.loads(body) if body else {}
                    except json.JSONDecodeError:
                        logger.error(
                            "gateway.invalid_json request_id=%s status_code=%s command_type=%s body_snippet=%s",
                            trace_id,
                            response.status,
                            command_prefix,
                            snippet,
                        )
                        raise GatewayResponseError("Gateway returned invalid JSON.")

                    if not isinstance(data, dict):
                        logger.error(
                            "gateway.invalid_format request_id=%s command_type=%s type=%s",
                            trace_id,
                            command_prefix,
                            type(data).__name__,
                        )
                        raise GatewayResponseError("Gateway response format is unsupported.")

                    return data
        except (aiohttp.ClientError, TimeoutError) as exc:
            transient = _is_likely_transient(exc)
            logger.warning(
                "gateway.network_error request_id=%s command_type=%s url=%s error_class=%s transient=%s message=%s",
                trace_id,
                command_prefix,
                gateway_url,
                exc.__class__.__name__,
                transient,
                str(exc),
            )
            if transient and attempt < retries:
                # Small jitter helps avoid synchronized retries under shared failure.
                await asyncio.sleep(backoff_seconds + random.uniform(0.0, 0.15))
                continue
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


async def run_gateway_command(
    user_id: str,
    command_text: str,
    image_url: str | None = None,
    discord_channel_id: str | None = None,
    request_id: str | None = None,
    source: str = "discord",
) -> str:
    """Execute a command through the AI gateway with clean user-facing failures."""
    try:
        data = await call_ai_gateway(
            user_id=user_id,
            command_text=command_text,
            image_url=image_url,
            request_id=request_id,
            discord_channel_id=discord_channel_id,
            source=source,
        )
    except GatewayUnavailableError:
        return GATEWAY_UNAVAILABLE_MESSAGE
    except GatewayResponseError as exc:
        return f"❌ {exc}"
    except Exception:
        logger.exception(
            "gateway.unhandled_exception request_id=%s source=%s discord_user_id=%s discord_channel_id=%s command_type=%s",
            request_id or "unknown",
            source,
            str(user_id),
            discord_channel_id or "unknown",
            _command_prefix(command_text),
        )
        return "❌ Unexpected error while processing your request."

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


async def ask_ollama(
    user_id: str,
    prompt: str,
    request_id: str | None = None,
    discord_channel_id: str | None = None,
) -> str:
    """Run /ask through the AI gateway."""
    if not prompt.strip():
        return "⚠️ Please provide a prompt for /ask."
    return await run_gateway_command(
        user_id=user_id,
        command_text=f"ask/{prompt.strip()}",
        request_id=request_id,
        discord_channel_id=discord_channel_id,
        source="discord-slash-ask",
    )


async def analyze_ollama(
    user_id: str,
    user_input: str,
    request_id: str | None = None,
    discord_channel_id: str | None = None,
) -> str:
    """Run /analyze through the AI gateway."""
    if not user_input.strip():
        return "⚠️ Please provide text/data for /analyze."
    return await run_gateway_command(
        user_id=user_id,
        command_text=f"analyze/{user_input.strip()}",
        request_id=request_id,
        discord_channel_id=discord_channel_id,
        source="discord-slash-analyze",
    )


async def detect_yolo(
    user_id: str,
    image_url: str | None,
    request_id: str | None = None,
    discord_channel_id: str | None = None,
) -> str:
    """Run /detect through the AI gateway."""
    if not image_url:
        return "⚠️ Please provide an image URL for /detect."
    return await run_gateway_command(
        user_id=user_id,
        command_text="detect/image",
        image_url=image_url,
        request_id=request_id,
        discord_channel_id=discord_channel_id,
        source="discord-slash-detect",
    )
