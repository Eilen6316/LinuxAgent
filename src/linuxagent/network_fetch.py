"""Safe, policy-gated HTTP fetch helper with SSRF guards."""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol, TypeAlias
from urllib.parse import SplitResult, quote, urljoin, urlsplit, urlunsplit

from .network_policy import NetworkPolicySettings, evaluate_network_policy

DEFAULT_FETCH_USER_AGENT = "LinuxAgent/4.1 safe-fetch"
MAX_REDIRECTS = 5
HTTP_PORT = 80
HTTPS_PORT = 443
HTTP_SUCCESS_MIN = 200
HTTP_REDIRECT_MIN = 300
HTTP_REDIRECT_MAX = 399
METADATA_IPV4 = ipaddress.IPv4Address("169.254.169.254")
SAFE_PATH_CHARS = "/%:@!$&'()*+,;="
SAFE_QUERY_CHARS = "/%:@!$&'()*+,;=?"
LOCALHOST_NAMES = frozenset({"localhost", "localhost.localdomain"})


class NetworkAccessError(ValueError):
    """Raised when a fetch request violates network policy or SSRF guards."""


class NetworkAuditSink(Protocol):
    def record_network_decision(
        self,
        *,
        target_domain: str,
        decision: str,
        matched_rule: str,
        reason: str,
        trace_id: str | None = None,
    ) -> None: ...


class FetchNetworkSettings(NetworkPolicySettings, Protocol):
    max_response_bytes: int
    timeout_seconds: float


@dataclass(frozen=True)
class FetchTarget:
    url: str
    scheme: str
    host: str
    connect_host: str
    port: int
    address: str
    request_target: str
    host_header: str


@dataclass(frozen=True)
class FetchTransportResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes
    truncated: bool = False


@dataclass(frozen=True)
class FetchResponse:
    url: str
    status: int
    content_type: str
    content: str
    truncated: bool
    redirects: int

    def to_record(self) -> dict[str, object]:
        return {
            "url": self.url,
            "status": self.status,
            "content_type": self.content_type,
            "content": self.content,
            "truncated": self.truncated,
            "redirects": self.redirects,
        }


Resolver: TypeAlias = Callable[[str, int], tuple[str, ...]]
Transport: TypeAlias = Callable[[FetchTarget, str, int, float], FetchTransportResponse]


def safe_fetch_url(
    config: FetchNetworkSettings,
    url: str,
    *,
    method: str = "GET",
    audit: NetworkAuditSink | None = None,
    trace_id: str | None = None,
    resolver: Resolver | None = None,
    transport: Transport | None = None,
) -> FetchResponse:
    request_method = _normalize_method(method)
    current_url = _absolute_url(url)
    redirects = 0
    resolve = resolver or resolve_host_addresses
    send = transport or socket_fetch_transport
    while True:
        target = validate_fetch_target(
            config,
            current_url,
            audit=audit,
            trace_id=trace_id,
            resolver=resolve,
        )
        response = send(target, request_method, config.max_response_bytes, config.timeout_seconds)
        location = _redirect_location(response)
        if location is None:
            return _fetch_response(target.url, response, redirects)
        if redirects >= MAX_REDIRECTS:
            _raise_redirect_limit(audit, target.host, trace_id)
        current_url = _redirect_url(target.url, location)
        redirects += 1


def validate_fetch_target(
    config: FetchNetworkSettings,
    url: str,
    *,
    audit: NetworkAuditSink | None = None,
    trace_id: str | None = None,
    resolver: Resolver | None = None,
) -> FetchTarget:
    parsed = _parse_fetch_url(url)
    host = parsed.hostname or ""
    connect_host = _connect_host(host)
    port = _url_port(parsed)
    decision = evaluate_network_policy(config, connect_host)
    _record_network_decision(
        audit,
        decision.target_domain or host,
        decision.decision.value,
        decision.matched_rule,
        decision.reason,
        trace_id,
    )
    if not decision.allowed:
        raise NetworkAccessError(decision.reason)
    address = _validated_address(
        connect_host,
        port,
        resolver or resolve_host_addresses,
        audit,
        trace_id,
    )
    return FetchTarget(
        url=urlunsplit(parsed),
        scheme=parsed.scheme,
        host=host,
        connect_host=connect_host,
        port=port,
        address=address,
        request_target=_request_target(parsed.path, parsed.query),
        host_header=_host_header(host, port, parsed.scheme),
    )


def resolve_host_addresses(host: str, port: int) -> tuple[str, ...]:
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise NetworkAccessError(f"DNS resolution failed for {host}") from exc
    addresses = tuple(dict.fromkeys(str(record[4][0]) for record in records))
    if not addresses:
        raise NetworkAccessError(f"DNS resolution returned no addresses for {host}")
    return addresses


def socket_fetch_transport(
    target: FetchTarget,
    method: str,
    max_response_bytes: int,
    timeout_seconds: float,
) -> FetchTransportResponse:
    sock = _open_socket(target, timeout_seconds)
    try:
        _send_http_request(sock, target, method)
        response = http.client.HTTPResponse(sock)
        response.begin()
        body = b"" if method == "HEAD" else response.read(max_response_bytes + 1)
        truncated = len(body) > max_response_bytes
        return FetchTransportResponse(
            status=response.status,
            headers=_response_headers(response),
            body=body[:max_response_bytes] if truncated else body,
            truncated=truncated,
        )
    finally:
        sock.close()


def is_restricted_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    mapped = ip.ipv4_mapped if isinstance(ip, ipaddress.IPv6Address) else None
    if mapped is not None:
        return is_restricted_ip(mapped)
    if isinstance(ip, ipaddress.IPv4Address) and ip == METADATA_IPV4:
        return True
    if ip.is_loopback or ip.is_private or ip.is_link_local:
        return True
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return True
    return not ip.is_global


def _normalize_method(method: str) -> str:
    normalized = method.strip().upper()
    if normalized not in {"GET", "HEAD"}:
        raise NetworkAccessError("only GET and HEAD methods are supported")
    return normalized


def _absolute_url(url: str) -> str:
    value = url.strip()
    if not value:
        raise NetworkAccessError("URL must not be empty")
    return urlunsplit(_parse_fetch_url(value))


def _raise_redirect_limit(
    audit: NetworkAuditSink | None,
    host: str,
    trace_id: str | None,
) -> None:
    _record_network_decision(
        audit,
        host,
        "deny",
        "network.redirect_limit",
        "redirect limit exceeded",
        trace_id,
    )
    raise NetworkAccessError("redirect limit exceeded")


def _parse_fetch_url(url: str) -> SplitResult:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise NetworkAccessError("only http and https URLs are supported")
    if parsed.username is not None or parsed.password is not None:
        raise NetworkAccessError("URLs with userinfo are not supported")
    if not parsed.hostname:
        raise NetworkAccessError("URL must include a host")
    try:
        _url_port(parsed)
    except ValueError as exc:
        raise NetworkAccessError("URL port is invalid") from exc
    if parsed.fragment:
        parsed = parsed._replace(fragment="")
    return parsed


def _default_port(scheme: str) -> int:
    return HTTPS_PORT if scheme == "https" else HTTP_PORT


def _url_port(parsed: SplitResult) -> int:
    return parsed.port or _default_port(parsed.scheme)


def _connect_host(host: str) -> str:
    literal = _ip_address(host)
    if literal is not None:
        return str(literal)
    if host.strip().rstrip(".").casefold() in LOCALHOST_NAMES:
        raise NetworkAccessError("localhost hostnames are restricted")
    try:
        return host.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise NetworkAccessError("URL host is invalid") from exc


def _validated_address(
    host: str,
    port: int,
    resolver: Resolver,
    audit: NetworkAuditSink | None,
    trace_id: str | None,
) -> str:
    literal = _ip_address(host)
    if literal is not None:
        _ensure_public_ip(host, literal, audit, trace_id)
        return str(literal)
    addresses = tuple(_ip_address(address) for address in resolver(host, port))
    if not addresses or any(address is None for address in addresses):
        raise NetworkAccessError(f"DNS resolution returned invalid addresses for {host}")
    for address in addresses:
        assert address is not None
        _ensure_public_ip(host, address, audit, trace_id)
    return str(addresses[0])


def _ip_address(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value.strip("[]"))
    except ValueError:
        return None


def _ensure_public_ip(
    host: str,
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
    audit: NetworkAuditSink | None,
    trace_id: str | None,
) -> None:
    if not is_restricted_ip(ip):
        return
    reason = f"resolved IP {ip} is restricted"
    _record_network_decision(
        audit,
        host,
        "deny",
        "network.ssrf_restricted_ip",
        reason,
        trace_id,
    )
    raise NetworkAccessError(reason)


def _request_target(path: str, query: str) -> str:
    safe_path = quote(path or "/", safe=SAFE_PATH_CHARS)
    if not query:
        return safe_path
    return f"{safe_path}?{quote(query, safe=SAFE_QUERY_CHARS)}"


def _host_header(host: str, port: int, scheme: str) -> str:
    formatted_host = _connect_host(host)
    formatted = (
        f"[{formatted_host}]"
        if ":" in formatted_host and not formatted_host.startswith("[")
        else formatted_host
    )
    if port == _default_port(scheme):
        return formatted
    return f"{formatted}:{port}"


def _open_socket(target: FetchTarget, timeout_seconds: float) -> socket.socket:
    raw = socket.create_connection((target.address, target.port), timeout=timeout_seconds)
    if target.scheme == "http":
        return raw
    try:
        return ssl.create_default_context().wrap_socket(raw, server_hostname=target.connect_host)
    except Exception:
        raw.close()
        raise


def _send_http_request(sock: socket.socket, target: FetchTarget, method: str) -> None:
    request = "\r\n".join(
        (
            f"{method} {target.request_target} HTTP/1.1",
            f"Host: {target.host_header}",
            f"User-Agent: {DEFAULT_FETCH_USER_AGENT}",
            "Accept: text/plain,text/html,application/json,*/*;q=0.5",
            "Accept-Language: en-US,en;q=0.5",
            "Connection: close",
            "",
            "",
        )
    )
    sock.sendall(request.encode("ascii"))


def _response_headers(response: http.client.HTTPResponse) -> dict[str, str]:
    return {key.lower(): value for key, value in response.getheaders()}


def _redirect_location(response: FetchTransportResponse) -> str | None:
    if response.status < HTTP_REDIRECT_MIN or response.status > HTTP_REDIRECT_MAX:
        return None
    location = response.headers.get("location")
    return location.strip() if isinstance(location, str) and location.strip() else None


def _redirect_url(base_url: str, location: str) -> str:
    return _absolute_url(urljoin(base_url, location))


def _fetch_response(
    url: str,
    response: FetchTransportResponse,
    redirects: int,
) -> FetchResponse:
    return FetchResponse(
        url=url,
        status=response.status,
        content_type=response.headers.get("content-type", "application/octet-stream"),
        content=response.body.decode("utf-8", errors="replace"),
        truncated=response.truncated,
        redirects=redirects,
    )


def _record_network_decision(
    audit: NetworkAuditSink | None,
    target_domain: str,
    decision: str,
    matched_rule: str,
    reason: str,
    trace_id: str | None,
) -> None:
    if audit is None:
        return
    audit.record_network_decision(
        target_domain=target_domain,
        decision=decision,
        matched_rule=matched_rule,
        reason=reason,
        trace_id=trace_id,
    )
