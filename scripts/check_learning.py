"""Validate the offline teach workspace with Python's standard library.
Run from any cwd: python scripts/check_learning.py
This is structural evidence, not learner mastery or browser/visual acceptance.
"""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
import json
import re

ROOT = Path(__file__).resolve().parents[1]


class Page(HTMLParser):
    def __init__(self, path):
        super().__init__(convert_charrefs=True)
        self.path = path
        self.tags = []
        self.text = []
        self.ids = []
        self.links = []
        self.choices = []
        self.capture_choice = False
        self.choice = ""
        self.stack = []
        self.errors = []
        self.feed(path.read_text(encoding="utf-8"))
        self.close()
        if self.stack:
            self.errors.append(f"Unclosed tags: {self.stack}")

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append((tag, a))
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append(tag)
        if "id" in a:
            self.ids.append(a["id"])
        for key in ("href", "src"):
            if key in a:
                self.links.append(a[key])
        if tag == "span" and a.get("class") == "choice-text":
            self.capture_choice, self.choice = True, ""

    def handle_endtag(self, tag):
        if tag == "span" and self.capture_choice:
            self.choices.append(self.choice)
            self.capture_choice = False
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"Unbalanced closing tag {tag}, stack={self.stack}")
        else:
            self.stack.pop()

    def handle_data(self, data):
        self.text.append(data)
        if self.capture_choice:
            self.choice += data


def main():
    errors = []
    def check(condition, message):
        if not condition:
            errors.append(message)

    manifest = json.loads((ROOT / "assets/splendor-course.json").read_text(encoding="utf-8"))
    lessons = manifest["lessons"]
    check(manifest["mastery"] == "not_assessed", "Do not invent mastery")
    check([l["id"] for l in lessons] == list(range(1, 17)), "Expected 16 sequential goals")
    paths = sorted((ROOT / "lessons").glob("*.html")) + sorted((ROOT / "reference").glob("*.html"))
    pages = {p.resolve(): Page(p) for p in paths}
    check(len(pages) == 19, "Expected 16 lessons, index and two references")
    link_count = 0
    for path, page in pages.items():
        label = str(path.relative_to(ROOT))
        check(not page.errors, f"{label}: {page.errors}")
        check(len(page.ids) == len(set(page.ids)), f"{label}: duplicate IDs")
        check(sum(tag == "h1" for tag, _ in page.tags) == 1, f"{label}: one h1 required")
        check(any(tag == "html" and a.get("lang") == "zh-CN" for tag, a in page.tags), f"{label}: language missing")
        check(any(tag == "main" and a.get("id") == "main" for tag, a in page.tags), f"{label}: main/skip target missing")
        for tag, a in page.tags:
            if tag in {"script", "link", "img", "iframe"}:
                url = a.get("src", a.get("href", ""))
                check(not urlsplit(url).scheme and not url.startswith("//"), f"{label}: remote runtime asset {url}")
        for url in page.links:
            parts = urlsplit(url)
            if parts.scheme or parts.netloc:
                check(parts.scheme == "https", f"{label}: unsupported external URL {url}")
                continue
            target = (path.parent / unquote(parts.path)).resolve() if parts.path else path
            check(target.is_relative_to(ROOT), f"{label}: local link escapes repository: {url}")
            check(target.is_file(), f"{label}: broken link {url}")
            if parts.fragment and target.suffix == ".html" and target in pages:
                check(unquote(parts.fragment) in pages[target].ids, f"{label}: missing anchor {url}")
            link_count += 1
    index_links = pages[(ROOT / "lessons/index.html").resolve()].links
    for lesson in lessons:
        page = pages.get((ROOT / lesson["path"]).resolve())
        check(page is not None, f"Missing goal page {lesson['path']}")
        if page is None:
            continue
        text = "".join(page.text)
        check(lesson["goal"] in text, f"Goal mismatch {lesson['id']}")
        check(lesson["title"] in text, f"Title mismatch {lesson['id']}")
        check(Path(lesson["path"]).name in index_links, f"Index missing goal {lesson['id']}")
        check({"goal", "case", "mechanism", "practice", "retrieval", "sources"}.issubset(page.ids), f"Incomplete lesson {lesson['id']}")
        check(len(text) > 1000, f"Thin/placeholder lesson {lesson['id']}")
        check(len(page.choices) == 3 and len({len(s) for s in page.choices}) == 1, f"Unequal quiz choices {lesson['id']}: {page.choices}")
        quizzes = [a for t, a in page.tags if t == "form" and "data-quiz" in a]
        check(len(quizzes) == 1, f"Quiz missing {lesson['id']}")
        if quizzes:
            q = quizzes[0]
            check(q.get("data-correct") in {"0", "1", "2"}, f"Invalid correct answer {lesson['id']}")
            check(bool(q.get("data-explanation")), f"No feedback explanation {lesson['id']}")
        for source in [lesson["primary"], *lesson["sources"]]:
            url = source if source.startswith("https:") else "../" + source
            check(url in page.links, f"Source missing {lesson['id']}: {source}")
    research = pages[(ROOT / "reference/research-map.html").resolve()].links
    for doc in (ROOT / "docs").glob("m[0-9]*.md"):
        check("../docs/" + doc.name in research, f"Milestone absent from research map: {doc.name}")
    for name in ("MISSION.md", "RESOURCES.md", "NOTES.md"):
        content = (ROOT / name).read_text(encoding="utf-8")
        for url in re.findall(r"\]\(([^)]+)\)", content):
            if not urlsplit(url).scheme:
                check((ROOT / url.split("#")[0]).is_file(), f"Broken Markdown link {name}: {url}")
    js = (ROOT / "assets/learning.js").read_text(encoding="utf-8")
    check(not re.search(r"\b(fetch|XMLHttpRequest|localStorage|sessionStorage)\b", js), "Runtime must not network or persist progress")
    if errors:
        print("FAIL:")
        print("\n".join("- " + e for e in errors))
        raise SystemExit(1)
    print(f"PASS: {len(lessons)} goals; {len(pages)} HTML pages; {link_count} local URLs; equal-length quizzes; complete sources/map; no remote runtime assets.")


if __name__ == "__main__":
    main()
