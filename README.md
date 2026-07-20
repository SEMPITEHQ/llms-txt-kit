# llms-txt-kit

Generate and validate [`llms.txt`](https://llmstxt.org) files — CLI and Python library, **zero dependencies**, Python 3.8+.

`llms.txt` is a plain-text file at the root of your site that gives large language models a curated map of it: a title, a one-paragraph summary, and links to the pages that matter. Think `robots.txt`, but instead of *where crawlers may go* it says *what your site means*.

```bash
pip install llms-txt-kit

# build one from your sitemap, in one command
llms-txt generate --from-sitemap acme.coffee \
  --name "Acme Coffee" --description "Specialty roaster in Brooklyn." -o llms.txt

# check the one you already have
llms-txt validate acme.coffee
```

Prefer a web form? The hosted version is free at [sempite.com/tools/llms-txt-generator](https://sempite.com/tools/llms-txt-generator) — no install, no signup.

## Why bother

AI assistants increasingly answer questions *about* businesses instead of linking to them. `llms.txt` is the one file where you get to state, in your own words and in a form models can parse, what your site is and which pages matter. It costs nothing to publish, and writing one forces a genuinely useful exercise: summarising your business in a paragraph a machine can quote.

## CLI

### generate

```bash
# explicit links
llms-txt generate \
  --name "Acme Coffee" \
  --description "Specialty coffee roaster in Brooklyn, shipping nationwide." \
  --url acme.coffee \
  --link "Menu|/menu|What we're pouring this week" \
  --link "Wholesale|/wholesale|Bulk and cafe accounts" \
  --optional "Press kit|/press" \
  -o llms.txt

# or derive everything from the sitemap
llms-txt generate --from-sitemap acme.coffee \
  --name "Acme Coffee" --description "Specialty roaster." \
  --limit 25 --titles
```

`--from-sitemap` reads `sitemap.xml` (following sitemap indexes), groups URLs into sections by their first path segment, folds one-off segments into **Pages** so you don't get a heading per page, and routes boilerplate — privacy, terms, accessibility — into the conventional `## Optional` section. `--titles` fetches each page for its real `<title>` and meta description instead of deriving names from slugs.

| Flag | Meaning |
|---|---|
| `--name` / `--description` | required: the H1 and the `>` summary |
| `--url` | canonical site; also absolutises relative `--link` URLs |
| `--link "Title\|URL\|note"` | a key page — repeatable |
| `--optional "Title\|URL\|note"` | a page for `## Optional` — repeatable |
| `--from-sitemap URL` | build from a sitemap instead of `--link` flags |
| `--limit` / `--titles` | cap link count; fetch real titles |
| `--no-credit` | omit the trailing credit comment |
| `-o FILE` | write to a file instead of stdout |

### validate

```bash
llms-txt validate acme.coffee        # fetches https://acme.coffee/llms.txt
llms-txt validate ./llms.txt         # local file
llms-txt validate acme.coffee --json # machine-readable
```

```
https://acme.coffee/llms.txt
----------------------------
  PASS  llms.txt is reachable  —  https://acme.coffee/llms.txt
  PASS  Starts with an H1 title  —  # Acme Coffee
  PASS  Exactly one H1  —  One H1
  PASS  Has a blockquote summary  —  Specialty coffee roaster in Brooklyn…
  PASS  Links to key pages  —  7 link(s)
  WARN  Links have descriptions  —  2/7 links annotated
  PASS  Reasonable size (under 100 KB)  —  4 KB

12/13 checks passed · 0 error(s), 1 warning(s)
```

**Exit codes** make it CI-friendly: `0` valid, `1` errors found (`--strict` also fails on warnings), `2` bad usage or unreachable target.

```yaml
# keep llms.txt honest on every deploy
- run: pipx run llms-txt-kit validate ./public/llms.txt --strict
```

## Python API

```python
from llmstxt import generate, parse, validate, validate_url, from_sitemap

text = generate(
    "Acme Coffee",
    "Specialty coffee roaster in Brooklyn, shipping nationwide.",
    links=[("Menu", "https://acme.coffee/menu", "What we pour")],
    optional_links=[("Press kit", "https://acme.coffee/press")],
    url="https://acme.coffee",
)

report = validate_url("acme.coffee")
print(report.ok, len(report.errors), len(report.warnings))
for check in report.checks:
    print(check.status, check.label, check.detail)

doc = parse(text)
print(doc.title, doc.summary, [l.url for l in doc.links])

text = from_sitemap("acme.coffee", "Acme Coffee", "Specialty roaster.", limit=25)
```

`generate()` accepts links as `Link` objects, `(title, url, note)` tuples, or dicts — whichever your data already looks like. `validate()` never raises on malformed input; it reports.

## What validation checks

Errors (the file is not spec-shaped): reachable, non-empty, not HTML, starts with a single `# H1`, has at least one link, all links absolute.
Warnings (it works, but could be better): blockquote summary present, three or more links, HTTPS everywhere, no duplicate URLs, links annotated with notes, sections used, under 100 KB.

## Where the file goes

Serve it at the root of your domain as plain text — `https://yoursite.com/llms.txt` — exactly like `robots.txt`. Nginx:

```nginx
location = /llms.txt { default_type text/plain; }
```

## Related

- The specification: [llmstxt.org](https://llmstxt.org)
- The spec authors' own Python package: [`llms-txt`](https://pypi.org/project/llms-txt/) (parsing/expansion oriented) — this project is unaffiliated and complementary, focused on generating and linting the file itself
- Hosted, no-install version of this tool: [sempite.com/tools/llms-txt-generator](https://sempite.com/tools/llms-txt-generator)
- Can AI actually read your site? [Free AI Readiness Score](https://sempite.com/tools/ai-readiness-score) — 21 technical checks
- Does AI cite you? [Free AI Citation Checker](https://sempite.com/tools/ai-citation-checker)

## Development

```bash
git clone https://github.com/SEMPITEHQ/llms-txt-kit
cd llms-txt-kit
python -m unittest discover -s tests -v
```

No dependencies, no build step, no test framework to install.

## License

MIT © [SEMPITE](https://sempite.com)
