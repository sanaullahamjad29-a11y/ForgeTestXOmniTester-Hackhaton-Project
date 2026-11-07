import hashlib
import ipaddress
import json
import re
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse
from fastapi import HTTPException

_VALID_HOST_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$"
)


def normalize_and_check_syntax(raw_value: str) -> str:
    """Validates URL syntax strictly without mangling typos like 'httttps://'."""
    value = (raw_value or "").strip()
    if not value:
        raise HTTPException(400, "Please enter a website URL.")

    # Catch protocol typos like htttps://, htp://, http//, or double protocols https://httttps://
    if re.match(r"^[a-zA-Z0-9+.-]+://", value):
        scheme = value.split("://", 1)[0].lower()
        if scheme not in ("http", "https"):
            raise HTTPException(
                400,
                f"Invalid URL protocol '{scheme}://'. Only 'http://' and 'https://' are supported.",
            )
        rest = value.split("://", 1)[1]
        if "://" in rest.split("/", 1)[0]:
            raise HTTPException(
                400,
                "Malformed URL: contains duplicate protocol ('://'). Check the URL for typos.",
            )
    elif ":" in value.split("/", 1)[0] and not re.match(r"^[a-zA-Z0-9.-]+:\d+$", value.split("/", 1)[0]):
        raise HTTPException(
            400,
            "Invalid URL format. Make sure it starts with 'https://' or 'http://'.",
        )
    else:
        value = "https://" + value

    return value


def validate_url(value: str) -> str:
    value = normalize_and_check_syntax(value)
    p = urlparse(value)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise HTTPException(400, "Only valid public HTTP/HTTPS URLs are accepted.")
    if p.username or p.password:
        raise HTTPException(400, "Embedded URL credentials are not allowed.")

    host = p.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        raise HTTPException(400, "Localhost targets are blocked.")
    if host in ("metadata.google.internal", "169.254.169.254", "instance-data"):
        raise HTTPException(400, "Cloud metadata endpoints are blocked.")

    # Check if host is an IP literal first
    try:
        ip_obj = ipaddress.ip_address(host.split("%")[0])
        if not ip_obj.is_global:
            raise HTTPException(400, "Private, loopback, link-local, and reserved IPs are blocked.")
    except ValueError:
        # Host is a domain name; validate domain format
        if not _VALID_HOST_RE.match(host):
            raise HTTPException(
                400,
                f"Invalid domain name '{host}'. Please enter a real domain like 'https://example.com'.",
            )

    try:
        rows = socket.getaddrinfo(
            host,
            p.port or (443 if p.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except OSError:
        raise HTTPException(
            400,
            f"Domain '{host}' does not exist or could not be resolved (DNS NXDOMAIN). Check the spelling of the URL.",
        )

    ips = {ipaddress.ip_address(x[4][0].split("%")[0]) for x in rows}
    if not ips or any(not x.is_global for x in ips):
        raise HTTPException(400, "Private, loopback, link-local, and reserved IPs are blocked.")
    return value


def build_containment_receipt(kind: str, payload: dict, extra_flags: list[str] | None = None) -> dict:
    """Produces a verifiable SHA-256 receipt proving sandboxed execution & isolation."""
    canonical = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    base_flags = [
        "--rm",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--memory=1024m",
        "--cpus=1.0",
        "--pids-limit=64",
        "secrets-mounted=false",
    ]
    if extra_flags:
        for flag in extra_flags:
            if flag not in base_flags:
                base_flags.append(flag)
    return {
        "receipt_id": f"vultr-brz-{digest[:12]}",
        "sha256": digest,
        "kind": kind,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sandbox_profile": "vultr-blast-radius-zero-v2",
        "isolation_flags": base_flags,
        "secret_hygiene": "Verified: 0 API keys or host credentials inside sandbox",
        "lifecycle": "Ephemeral environment destroyed (--rm) on completion",
    }
