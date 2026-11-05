"""Web search and page-fetch tools."""

from __future__ import annotations

import html
import ipaddress
import os
import re
import socket
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36 HermesAgent/0.1"
)

MAX_PAGE_CHARS = 9000


class WebError(RuntimeError):
    """Recoverable web tool error."""


def web_search(query: str, max_results: int = 5) -> str:
    query = str(query or "").strip()
    if not query:
        raise WebError("query must not be empty.")
    max_results = max(1, min(int(max_results or 5), 10))

    tavily_key = os.environ.get("TAVILY_API_KEY")
    if tavily_key:
        return _tavily_search(query, max_results, tavily_key)

    try:
        return _duckduckgo_search(query, max_results)
    except (httpx.HTTPError, WebError) as exc:
        return (
            f"Web search failed ({exc}).\n"
            "Tip: set TAVILY_API_KEY for a more reliable search backend, or "
            "use web_fetch on a known URL."
        )


def _tavily_search(query: str, max_results: int, api_key: str) -> str:
    try:
        response = httpx.post(
            "https://api.tavily.com/search",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
                "include_answer": True,
            },
            timeout=30.0,
            follow_redirects=True,
        )
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise WebError(f"Tavily search failed: {exc}") from exc

    results = data.get("results") or []
    if not results:
        return f"No web results for '{query}'."

    lines = [f"Search results for: {query}"]
    answer = (data.get("answer") or "").strip()
    if answer:
        lines.append(f"Summary: {answer}")
    for index, result in enumerate(results[:max_results], start=1):
        title = _clean_text(str(result.get("title") or "Untitled"))
        url = str(result.get("url") or "")
        snippet = _clean_text(str(result.get("content") or ""))
        lines.append(f"\n{index}. {title}\n   {url}\n   {snippet[:450]}")
    return "\n".join(lines)


def _duckduckgo_search(query: str, max_results: int) -> str:
    try:
        response = httpx.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.8"},
            timeout=30.0,
            follow_redirects=True,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise WebError(f"DuckDuckGo request failed: {exc}") from exc

    page = response.text
    link_pattern = re.compile(
        r'<a[^>]+class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    snippet_pattern = re.compile(
        r'<(?:a|div)[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</(?:a|div)>',
        re.IGNORECASE | re.DOTALL,
    )

    links = link_pattern.findall(page)
    snippets = snippet_pattern.findall(page)
    if not links:
        return (
            f"No web results parsed for '{query}'. DuckDuckGo may be rate-limiting "
            "or changed its markup; set TAVILY_API_KEY for reliable search."
        )

    lines = [f"Search results for: {query}"]
    for index, (raw_url, raw_title) in enumerate(links[:max_results]):
        title = _clean_text(raw_title) or "Untitled"
        url = _clean_ddg_url(raw_url)
        snippet = _clean_text(snippets[index]) if index < len(snippets) else ""
        lines.append(f"\n{index + 1}. {title}\n   {url}")
        if snippet:
            lines.append(f"   {snippet[:450]}")
    return "\n".join(lines)


def _clean_ddg_url(raw_url: str) -> str:
    url = html.unescape(raw_url)
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if query.get("uddg"):
        return unquote(query["uddg"][0])
    return url


def web_fetch(url: str, max_chars: int = MAX_PAGE_CHARS) -> str:
    url = str(url or "").strip()
    max_chars = max(500, min(int(max_chars or MAX_PAGE_CHARS), 30000))

    current_url = url
    try:
        for _ in range(5):
            _validate_public_url(current_url)
            response = httpx.get(
                current_url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept-Language": "en-US,en;q=0.8",
                },
                timeout=30.0,
                follow_redirects=False,
            )
            location = response.headers.get("location")
            if response.status_code in {301, 302, 303, 307, 308} and location:
                current_url = urljoin(current_url, location)
                continue
            break
        else:
            raise WebError("Too many redirects.")
    except httpx.HTTPError as exc:
        raise WebError(f"Could not fetch {url}: {exc}") from exc

    if response.status_code >= 400:
        raise WebError(f"{current_url} returned HTTP {response.status_code}.")

    content_type = response.headers.get("content-type", "").lower()
    if "html" in content_type or "<html" in response.text[:500].lower():
        title_match = re.search(r"<title[^>]*>(.*?)</title>", response.text, re.IGNORECASE | re.DOTALL)
        title = _clean_text(title_match.group(1)) if title_match else url
        text = _html_to_text(response.text)
        header = f"# {title}\nURL: {response.url}\n"
    elif content_type.startswith("text/") or "json" in content_type:
        text = response.text
        header = f"URL: {response.url}\n"
    else:
        raise WebError(
            f"Unsupported content type '{content_type or 'unknown'}'. "
            "web_fetch only handles text, JSON, and HTML pages."
        )

    text = text.strip()
    if not text:
        return f"{header}(page contained no readable text)"
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n... [truncated, {len(text) - max_chars} characters omitted]"
    return header + "\n" + text


def _validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise WebError("Only http:// and https:// URLs are supported.")
    host = parsed.hostname
    if not host:
        raise WebError("URL has no host.")
    default_port = 443 if parsed.scheme == "https" else 80
    try:
        addresses = socket.getaddrinfo(
            host, parsed.port or default_port, proto=socket.IPPROTO_TCP
        )
    except socket.gaierror as exc:
        raise WebError(f"Could not resolve host '{host}': {exc}") from exc

    for info in addresses:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if not ip.is_global:
            raise WebError(
                f"Blocked private or local address for '{host}'. "
                "web_fetch only allows public internet URLs."
            )


def _html_to_text(raw_html: str) -> str:
    text = re.sub(
        r"<(script|style|noscript|svg|iframe)[^>]*>.*?</\1>",
        " ",
        raw_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = re.sub(r"<(br|hr)\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(
        r"</(p|div|section|article|header|footer|li|tr|h[1-6]|blockquote|pre)>",
        "\n",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"<li[^>]*>", "\n- ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _clean_text(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    return " ".join(text.split())
