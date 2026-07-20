"""llms-txt-kit — generate, parse, and validate llms.txt files.

llms.txt is a plain-text file at the root of a website that gives large language
models a curated map of the site: a title, a short summary, and links to the
pages that matter. See https://llmstxt.org for the specification.

    from llmstxt import generate, validate_url

    print(generate("Acme Coffee", "Specialty roaster in Brooklyn.",
                   links=[("Menu", "https://acme.coffee/menu", "What we pour")]))

    report = validate_url("acme.coffee")
    print(report.ok, [c.label for c in report.errors])

Zero dependencies — standard library only. Python 3.8+.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence, Tuple, Union

__version__ = "0.1.0"
__all__ = [
    "Link", "Section", "Document", "Check", "Report",
    "generate", "parse", "validate", "validate_url", "from_sitemap",
    "fetch", "CREDIT",
]

USER_AGENT = f"llms-txt-kit/{__version__} (+https://github.com/SEMPITEHQ/llms-txt-kit)"
CREDIT = ("<!-- Generated with llms-txt-kit — "
          "https://sempite.com/tools/llms-txt-generator -->")
MAX_BYTES = 100_000          # spec-adjacent convention: keep llms.txt small
OPTIONAL_HEADING = "Optional"

_H1 = re.compile(r"^#\s+(.+?)\s*$")
_H2 = re.compile(r"^##\s+(.+?)\s*$")
_HEADING_ANY = re.compile(r"^(#{1,6})\s+")
_QUOTE = re.compile(r"^>\s?(.*)$")
_BULLET = re.compile(r"^[-*]\s+(.*)$")
_LINK = re.compile(r"^\[([^\]]+)\]\(\s*(\S+?)\s*\)\s*(?::\s*(.*))?$")


# ─────────────────────────────── data model ──────────────────────────────────

@dataclass
class Link:
    """One `- [title](url): note` entry."""
    title: str
    url: str
    note: str = ""

    def render(self) -> str:
        line = f"- [{self.title}]({self.url})"
        return f"{line}: {self.note}" if self.note else line


@dataclass
class Section:
    """An `## Heading` block and the links beneath it."""
    heading: str
    links: List[Link] = field(default_factory=list)
    prose: str = ""

    @property
    def is_optional(self) -> bool:
        return self.heading.strip().lower() == OPTIONAL_HEADING.lower()


@dataclass
class Document:
    """A parsed llms.txt file."""
    title: str = ""
    summary: str = ""
    prose: str = ""
    sections: List[Section] = field(default_factory=list)
    extra_h1: int = 0

    @property
    def links(self) -> List[Link]:
        return [l for s in self.sections for l in s.links]


@dataclass
class Check:
    """One validation result. `severity` is "error" or "warning"."""
    label: str
    ok: bool
    detail: str = ""
    severity: str = "error"

    @property
    def status(self) -> str:
        return "pass" if self.ok else self.severity


@dataclass
class Report:
    source: str
    checks: List[Check] = field(default_factory=list)
    document: Optional[Document] = None

    @property
    def errors(self) -> List[Check]:
        return [c for c in self.checks if not c.ok and c.severity == "error"]

    @property
    def warnings(self) -> List[Check]:
        return [c for c in self.checks if not c.ok and c.severity == "warning"]

    @property
    def passed(self) -> List[Check]:
        return [c for c in self.checks if c.ok]

    @property
    def ok(self) -> bool:
        """True when nothing failed at error severity."""
        return not self.errors

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "ok": self.ok,
            "passed": len(self.passed),
            "total": len(self.checks),
            "checks": [{"label": c.label, "status": c.status, "detail": c.detail}
                       for c in self.checks],
        }


LinkInput = Union[Link, Tuple, dict]


def _coerce_link(item: LinkInput) -> Optional[Link]:
    if isinstance(item, Link):
        return item if item.title and item.url else None
    if isinstance(item, dict):
        title, url, note = item.get("title", ""), item.get("url", ""), item.get("note", "")
    else:
        seq = list(item) + ["", "", ""]
        title, url, note = seq[0], seq[1], seq[2]
    title, url, note = str(title).strip(), str(url).strip(), str(note or "").strip()
    return Link(title, url, note) if title and url else None


# ─────────────────────────────── generate ────────────────────────────────────

def generate(name: str,
             description: str,
             links: Iterable[LinkInput] = (),
             sections: Sequence[Tuple[str, Iterable[LinkInput]]] = (),
             url: str = "",
             optional_links: Iterable[LinkInput] = (),
             prose: str = "",
             credit: bool = True) -> str:
    """Render a spec-shaped llms.txt.

    Args:
        name: the site or project name (becomes the H1).
        description: one-paragraph summary (becomes the blockquote).
        links: links for a default "Key pages" section.
        sections: explicit ``(heading, links)`` pairs, rendered in order.
        url: canonical site URL, used to absolutise relative links.
        optional_links: links for the conventional "## Optional" section —
            content an LLM may skip when its context budget is short.
        prose: free markdown inserted after the summary.
        credit: append an HTML-comment credit line.

    Returns:
        The llms.txt file contents as a string.
    """
    name, description = str(name).strip(), " ".join(str(description).split())
    if not name:
        raise ValueError("name is required")
    if not description:
        raise ValueError("description is required")
    base = str(url).strip().rstrip("/")
    if base and not base.startswith(("http://", "https://")):
        base = "https://" + base

    def absolutise(link: Link) -> Link:
        if link.url.startswith(("http://", "https://", "mailto:")):
            return link
        if base:
            return Link(link.title, f"{base}/{link.url.lstrip('/')}", link.note)
        return Link(link.title, "https://" + link.url.lstrip("/"), link.note)

    out: List[str] = [f"# {name}", "", f"> {description}", ""]
    if prose.strip():
        out += [prose.strip(), ""]

    blocks: List[Tuple[str, List[Link]]] = []
    default = [l for l in (_coerce_link(i) for i in links) if l]
    if default:
        blocks.append(("Key pages", default))
    for heading, items in sections:
        ls = [l for l in (_coerce_link(i) for i in items) if l]
        if ls:
            blocks.append((str(heading).strip() or "Links", ls))
    opt = [l for l in (_coerce_link(i) for i in optional_links) if l]
    if opt:
        blocks.append((OPTIONAL_HEADING, opt))

    for heading, ls in blocks:
        out.append(f"## {heading}")
        out.append("")
        out += [absolutise(l).render() for l in ls]
        out.append("")

    if base:
        out += [f"Canonical site: {base}", ""]
    if credit:
        out.append(CREDIT)
    return "\n".join(out).rstrip() + "\n"


# ───────────────────────────────── parse ─────────────────────────────────────

def parse(text: str) -> Document:
    """Parse llms.txt content into a :class:`Document` (lenient — never raises)."""
    doc = Document()
    current: Optional[Section] = None
    seen_h1 = False
    in_summary = False
    prose: List[str] = []

    for raw in (text or "").splitlines():
        line = raw.rstrip()
        m1 = _H1.match(line)
        if m1:
            if seen_h1:
                doc.extra_h1 += 1
            else:
                doc.title, seen_h1, in_summary = m1.group(1).strip(), True, True
            continue
        m2 = _H2.match(line)
        if m2:
            current = Section(m2.group(1).strip())
            doc.sections.append(current)
            in_summary = False
            continue
        mq = _QUOTE.match(line)
        if mq and in_summary:
            doc.summary = (doc.summary + " " + mq.group(1)).strip()
            continue
        if not line.strip():
            continue
        if line.lstrip().startswith("<!--"):
            continue
        in_summary = False
        mb = _BULLET.match(line.strip())
        if mb and current is not None:
            ml = _LINK.match(mb.group(1).strip())
            if ml:
                current.links.append(Link(ml.group(1).strip(), ml.group(2).strip(),
                                          (ml.group(3) or "").strip()))
            else:
                current.prose = (current.prose + "\n" + line).strip()
            continue
        if current is not None:
            current.prose = (current.prose + "\n" + line).strip()
        else:
            prose.append(line)
    doc.prose = "\n".join(prose).strip()
    return doc


# ──────────────────────────────── validate ───────────────────────────────────

def validate(text: str, source: str = "") -> Report:
    """Check llms.txt content against the spec's shape and common mistakes."""
    report = Report(source=source)
    add = report.checks.append
    body = text or ""
    stripped = body.lstrip()

    if not stripped:
        add(Check("File is not empty", False, "No content"))
        return report
    add(Check("File is not empty", True, f"{len(body):,} bytes"))

    looks_html = stripped[:2000].lower().startswith(("<!doctype", "<html")) or "<body" in stripped[:2000].lower()
    add(Check("Plain text or Markdown (not HTML)", not looks_html,
              "Looks like Markdown" if not looks_html
              else "The response is an HTML page — llms.txt must be served as plain text"))

    doc = parse(body)
    report.document = doc

    add(Check("Starts with an H1 title", bool(doc.title) and stripped.startswith("# "),
              f"# {doc.title}" if doc.title else "Add '# Your Site Name' as the first line"))
    add(Check("Exactly one H1", doc.extra_h1 == 0,
              "One H1" if doc.extra_h1 == 0
              else f"{doc.extra_h1 + 1} H1 headings — the spec expects a single title"))
    add(Check("Has a blockquote summary", bool(doc.summary),
              doc.summary[:90] if doc.summary
              else "Add '> one sentence about the site' under the title", "warning"))

    links = doc.links
    add(Check("Links to key pages", len(links) >= 3,
              f"{len(links)} link(s)" if links else "No links found — list your important pages",
              "error" if not links else "warning"))

    if links:
        relative = [l.url for l in links if not l.url.startswith(("http://", "https://", "mailto:"))]
        add(Check("All links absolute", not relative,
                  "All absolute" if not relative else f"{len(relative)} relative link(s): "
                  + ", ".join(relative[:3])))
        insecure = [l.url for l in links if l.url.startswith("http://")]
        add(Check("All links use HTTPS", not insecure,
                  "All HTTPS" if not insecure else f"{len(insecure)} http:// link(s)", "warning"))
        seen, dupes = set(), []
        for l in links:
            (dupes.append(l.url) if l.url in seen else seen.add(l.url))
        add(Check("No duplicate links", not dupes,
                  "No duplicates" if not dupes else f"{len(dupes)} repeated URL(s)", "warning"))
        described = sum(1 for l in links if l.note)
        add(Check("Links have descriptions", described >= max(1, len(links) // 2),
                  f"{described}/{len(links)} links annotated — notes help models pick the right page",
                  "warning"))

    add(Check("Uses section headings", bool(doc.sections),
              f"{len(doc.sections)} section(s)" if doc.sections
              else "Group links under '## Section' headings", "warning"))
    add(Check(f"Reasonable size (under {MAX_BYTES // 1000} KB)", len(body.encode()) < MAX_BYTES,
              f"{len(body.encode()) // 1024} KB", "warning"))
    return report


def fetch(url: str, timeout: float = 15.0) -> Tuple[str, str]:
    """Fetch a URL. Returns ``(text, content_type)``; raises urllib errors."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "text/plain, text/markdown, */*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(MAX_BYTES * 5)
        ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    charset = "utf-8"
    return raw.decode(charset, errors="replace"), ctype


def llms_txt_url(target: str) -> str:
    """Normalise a domain or URL into the URL of its llms.txt."""
    t = (target or "").strip()
    if not t:
        raise ValueError("a domain or URL is required")
    if not t.startswith(("http://", "https://")):
        t = "https://" + t
    parts = urllib.parse.urlsplit(t)
    path = parts.path or "/"
    if not path.endswith(".txt"):
        path = path.rstrip("/") + "/llms.txt"
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def validate_url(target: str, timeout: float = 15.0) -> Report:
    """Fetch ``<site>/llms.txt`` and validate it."""
    url = llms_txt_url(target)
    try:
        text, ctype = fetch(url, timeout)
    except urllib.error.HTTPError as e:
        r = Report(source=url)
        r.checks.append(Check("llms.txt is reachable", False, f"HTTP {e.code}"))
        return r
    except Exception as e:                                  # noqa: BLE001 - report, don't crash
        r = Report(source=url)
        r.checks.append(Check("llms.txt is reachable", False, str(e)))
        return r
    report = validate(text, source=url)
    report.checks.insert(0, Check("llms.txt is reachable", True, url))
    if ctype and not ctype.startswith("text/"):
        report.checks.insert(2, Check("Served as text/*", False,
                                      f"Content-Type: {ctype}", "warning"))
    return report


# ────────────────────────────── from sitemap ─────────────────────────────────

def _sitemap_urls(sitemap_url: str, timeout: float, depth: int = 0) -> List[str]:
    import xml.etree.ElementTree as ET
    text, _ = fetch(sitemap_url, timeout)
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    nested = [e.text.strip() for e in root.findall(".//s:sitemap/s:loc", ns) if e.text]
    urls = [e.text.strip() for e in root.findall(".//s:url/s:loc", ns) if e.text]
    if nested and depth < 2:
        for child in nested[:10]:
            urls += _sitemap_urls(child, timeout, depth + 1)
    return urls


_ACRONYMS = {"ai", "adhd", "api", "aeo", "geo", "seo", "faq", "iep", "llm", "llms",
             "url", "html", "css", "pdf", "crm", "b2b", "b2c", "ux", "ui", "nyc", "usa"}
# Pages every site has and no model needs first: routed to the "## Optional" section.
_BOILERPLATE = re.compile(
    r"/(privacy|terms|legal|accessibility|cookies?|dmca|disclaimer|refunds?|"
    r"returns?|shipping-policy|sitemap)(-[a-z]+)?/?$", re.I)


def _title_from_url(url: str) -> str:
    slug = urllib.parse.urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    if not slug:
        return "Home"
    slug = re.sub(r"\.(html?|php|aspx)$", "", slug)
    words = [w for w in re.split(r"[-_]+", slug) if w]
    if not words:
        return "Home"
    return " ".join(w.upper() if w.lower() in _ACRONYMS else w.capitalize() for w in words)


def _page_title(url: str, timeout: float) -> Tuple[str, str]:
    try:
        text, _ = fetch(url, timeout)
    except Exception:                                       # noqa: BLE001
        return "", ""
    head = text[:60000]
    t = re.search(r"<title[^>]*>(.*?)</title>", head, re.I | re.S)
    d = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
                  head, re.I | re.S)
    import html as _html
    title = _html.unescape(" ".join(t.group(1).split())) if t else ""
    desc = _html.unescape(" ".join(d.group(1).split())) if d else ""
    return title[:120], desc[:160]


def from_sitemap(sitemap_url: str,
                 name: str,
                 description: str,
                 limit: int = 25,
                 include_titles: bool = False,
                 timeout: float = 15.0,
                 credit: bool = True) -> str:
    """Build an llms.txt from a site's sitemap.xml.

    URLs are grouped into sections by their first path segment (``/blog/…`` →
    "Blog"); one-off segments fold into "Pages" so the file doesn't sprout a
    heading per page, and boilerplate (privacy, terms, accessibility …) is
    routed to the conventional "## Optional" section. With ``include_titles``
    each page is fetched so real titles and meta descriptions are used —
    accurate, but it costs one request per URL.
    """
    if not sitemap_url.startswith(("http://", "https://")):
        sitemap_url = "https://" + sitemap_url.lstrip("/")
    if not sitemap_url.rstrip("/").endswith(".xml"):
        sitemap_url = sitemap_url.rstrip("/") + "/sitemap.xml"
    urls = list(dict.fromkeys(_sitemap_urls(sitemap_url, timeout)))
    if not urls:
        raise ValueError(f"No URLs found in {sitemap_url}")

    parts = urllib.parse.urlsplit(urls[0])
    site = f"{parts.scheme}://{parts.netloc}"

    def path_of(u: str) -> str:
        return urllib.parse.urlsplit(u).path or "/"

    boilerplate = [u for u in urls if _BOILERPLATE.search(path_of(u))]
    main = [u for u in urls if u not in set(boilerplate)]

    groups: dict = {}
    for u in main:
        seg = path_of(u).strip("/").split("/")[0]
        heading = " ".join(w.upper() if w.lower() in _ACRONYMS else w.capitalize()
                           for w in re.split(r"[-_]+", seg) if w) if seg else "Pages"
        groups.setdefault(heading, []).append(u)

    pages = groups.pop("Pages", [])
    for heading in [h for h, g in groups.items() if len(g) < 2]:
        pages += groups.pop(heading)                    # no heading for a lone page
    pages.sort(key=lambda u: (path_of(u).strip("/").count("/"), path_of(u) != "/", path_of(u)))

    ordered: List[Tuple[str, List[str]]] = ([("Pages", pages)] if pages else [])
    ordered += sorted(groups.items(), key=lambda kv: -len(kv[1]))

    def to_links(us: Iterable[str]) -> List[Link]:
        out = []
        for u in us:
            title, note = _page_title(u, timeout) if include_titles else ("", "")
            out.append(Link(title or _title_from_url(u), u, note))
        return out

    per_section = max(3, limit // max(1, len(ordered)))
    sections: List[Tuple[str, List[Link]]] = []
    used = 0
    for heading, group in ordered:
        take = group[:min(per_section, limit - used)]
        if not take:
            break
        sections.append((heading, to_links(take)))
        used += len(take)
    return generate(name, description, sections=sections, url=site,
                    optional_links=to_links(boilerplate[:6]), credit=credit)
