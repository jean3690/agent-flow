"""公网网页抓取：统一的协议校验与内网地址拦截。

网页读取节点和智能体的 web_fetch 工具共用这一层，避免两处实现出现安全差异。
"""

from __future__ import annotations

import html as html_lib
import ipaddress
import re
import socket
from urllib.parse import urljoin, urlparse

import httpx

MAX_BYTES = 5_000_000
MAX_REDIRECTS = 3
USER_AGENT = "AgentFlow/0.1"


class WebFetchError(ValueError):
    """地址不合法或抓取失败；消息可直接展示给用户。"""


def blocked_reason(hostname: str) -> str | None:
    lowered = hostname.lower()
    if lowered in {"localhost", "localhost.localdomain"} or lowered.endswith(".local"):
        return "不允许访问内网地址"
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(hostname, None)}
    except socket.gaierror:
        return None
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return "不允许访问内网地址"
    return None


def _check_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise WebFetchError("仅支持 http/https 公网地址")
    if parsed.username or parsed.password:
        raise WebFetchError("地址不能包含账号密码")
    reason = blocked_reason(parsed.hostname)
    if reason:
        raise WebFetchError(reason)
    return url


def to_plain_text(body: str, content_type: str) -> str:
    if "html" in content_type.lower() or body.lstrip().startswith("<"):
        body = re.sub(r"(?is)<(script|style).*?</\1>", " ", body)
        body = re.sub(r"(?s)<[^>]+>", " ", body)
        body = html_lib.unescape(body)
    return re.sub(r"\s+", " ", body).strip()


async def fetch_public_text(url: str, *, timeout_ms: int = 15000, max_chars: int = 8000) -> dict:
    """抓取一个公网地址并返回纯文本；每次重定向都会重新校验目标主机。"""
    current = _check_url(url.strip())
    timeout = max(1000, min(int(timeout_ms), 60000))
    limit = max(200, min(int(max_chars), 50000))
    async with httpx.AsyncClient(timeout=timeout / 1000, follow_redirects=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            response = await client.get(current, headers={"User-Agent": USER_AGENT})
            location = response.headers.get("location")
            if response.is_redirect and location:
                current = _check_url(urljoin(current, location))
                continue
            response.raise_for_status()
            if len(response.content) > MAX_BYTES:
                raise WebFetchError("页面超过 5 MB 限制")
            content_type = response.headers.get("content-type", "")
            text = to_plain_text(response.text, content_type)
            truncated = len(text) > limit
            return {
                "url": str(response.url),
                "content": text[:limit],
                "charCount": min(len(text), limit),
                "truncated": truncated,
                "contentType": content_type,
            }
    raise WebFetchError("重定向次数过多")
