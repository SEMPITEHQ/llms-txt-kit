"""Tests for llms-txt-kit. Standard library only: python -m unittest discover -s tests"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from llmstxt import (CREDIT, Link, generate, llms_txt_url,  # noqa: E402
                     parse, validate)
from llmstxt.cli import build_parser  # noqa: E402

SAMPLE = """# Acme Coffee

> Specialty coffee roaster in Brooklyn, shipping nationwide.

## Key pages

- [Menu](https://acme.coffee/menu): What we pour this week
- [Wholesale](https://acme.coffee/wholesale)

## Optional

- [Press kit](https://acme.coffee/press)
"""


class TestGenerate(unittest.TestCase):
    def test_shape(self):
        out = generate("Acme Coffee", "Specialty roaster.",
                       links=[("Menu", "https://acme.coffee/menu", "What we pour")])
        lines = out.splitlines()
        self.assertEqual(lines[0], "# Acme Coffee")
        self.assertIn("> Specialty roaster.", out)
        self.assertIn("## Key pages", out)
        self.assertIn("- [Menu](https://acme.coffee/menu): What we pour", out)
        self.assertIn(CREDIT, out)

    def test_credit_is_a_comment_not_a_second_h1(self):
        out = generate("Acme", "Desc.", links=[("A", "https://a.com")])
        self.assertEqual(sum(1 for l in out.splitlines() if l.startswith("# ")), 1)
        self.assertTrue(validate(out).ok)

    def test_no_credit(self):
        self.assertNotIn(CREDIT, generate("Acme", "Desc.", credit=False))

    def test_relative_links_absolutised(self):
        out = generate("Acme", "Desc.", links=[("About", "/about")], url="acme.coffee")
        self.assertIn("(https://acme.coffee/about)", out)

    def test_link_input_forms(self):
        out = generate("Acme", "Desc.", links=[
            Link("A", "https://a.com", "note"),
            ("B", "https://b.com"),
            {"title": "C", "url": "https://c.com", "note": "n"},
            ("", "https://skipped.com"),      # dropped: no title
        ])
        for expected in ("[A]", "[B]", "[C]"):
            self.assertIn(expected, out)
        self.assertNotIn("skipped", out)

    def test_sections_and_optional(self):
        out = generate("Acme", "Desc.",
                       sections=[("Guides", [("Brewing", "https://a.co/brew")])],
                       optional_links=[("Press", "https://a.co/press")])
        self.assertIn("## Guides", out)
        self.assertIn("## Optional", out)
        self.assertLess(out.index("## Guides"), out.index("## Optional"))

    def test_requires_name_and_description(self):
        for bad in (("", "d"), ("n", "")):
            with self.assertRaises(ValueError):
                generate(*bad)


class TestParse(unittest.TestCase):
    def test_parses_sample(self):
        doc = parse(SAMPLE)
        self.assertEqual(doc.title, "Acme Coffee")
        self.assertTrue(doc.summary.startswith("Specialty coffee roaster"))
        self.assertEqual([s.heading for s in doc.sections], ["Key pages", "Optional"])
        self.assertEqual(len(doc.links), 3)
        self.assertEqual(doc.links[0].note, "What we pour this week")
        self.assertEqual(doc.links[1].note, "")
        self.assertTrue(doc.sections[1].is_optional)

    def test_round_trip(self):
        doc = parse(generate("Acme", "Desc.", links=[("Menu", "https://a.co/menu", "n")]))
        self.assertEqual(doc.title, "Acme")
        self.assertEqual(doc.links[0].url, "https://a.co/menu")

    def test_lenient_on_garbage(self):
        self.assertEqual(parse("no headings here\njust text").title, "")


class TestValidate(unittest.TestCase):
    def test_valid_document(self):
        report = validate(SAMPLE)
        self.assertTrue(report.ok, [c.label for c in report.errors])

    def test_missing_h1_is_an_error(self):
        report = validate("> just a summary\n\n- [A](https://a.com)")
        self.assertFalse(report.ok)
        self.assertIn("Starts with an H1 title", [c.label for c in report.errors])

    def test_multiple_h1_flagged(self):
        report = validate("# One\n\n> s\n\n## S\n\n- [A](https://a.com)\n\n# Two\n")
        self.assertIn("Exactly one H1", [c.label for c in report.errors])

    def test_html_response_flagged(self):
        report = validate("<!doctype html><html><body>nope</body></html>")
        self.assertFalse(report.ok)

    def test_no_links_is_an_error(self):
        self.assertFalse(validate("# T\n\n> summary only\n").ok)

    def test_relative_and_insecure_links(self):
        report = validate("# T\n\n> s\n\n## S\n\n- [A](/rel)\n- [B](http://b.com)\n- [C](https://c.com)\n")
        self.assertIn("All links absolute", [c.label for c in report.errors])
        self.assertIn("All links use HTTPS", [c.label for c in report.warnings])

    def test_duplicates_warn(self):
        report = validate("# T\n\n> s\n\n## S\n\n- [A](https://a.com)\n- [B](https://a.com)\n- [C](https://c.com)\n")
        self.assertIn("No duplicate links", [c.label for c in report.warnings])

    def test_empty(self):
        self.assertFalse(validate("").ok)

    def test_as_dict(self):
        d = validate(SAMPLE).as_dict()
        self.assertTrue(d["ok"])
        self.assertEqual(d["total"], len(d["checks"]))


class TestUrlHelpers(unittest.TestCase):
    def test_llms_txt_url(self):
        for given, expected in (
            ("acme.coffee", "https://acme.coffee/llms.txt"),
            ("https://acme.coffee", "https://acme.coffee/llms.txt"),
            ("https://acme.coffee/", "https://acme.coffee/llms.txt"),
            ("https://acme.coffee/llms.txt", "https://acme.coffee/llms.txt"),
            ("https://acme.coffee/docs", "https://acme.coffee/docs/llms.txt"),
        ):
            self.assertEqual(llms_txt_url(given), expected)

    def test_requires_target(self):
        with self.assertRaises(ValueError):
            llms_txt_url("")


class TestCli(unittest.TestCase):
    def test_parser_wires_subcommands(self):
        p = build_parser()
        a = p.parse_args(["generate", "--name", "N", "--description", "D"])
        self.assertEqual(a.name, "N")
        b = p.parse_args(["validate", "acme.coffee", "--strict"])
        self.assertTrue(b.strict)


if __name__ == "__main__":
    unittest.main()
