"""Check the public documents as served, without relying on a site framework."""

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest


SITE = Path(__file__).resolve().parents[1] / "site"
PAGES = ("index.html", "privacidade.html", "termos.html")


class Document(HTMLParser):
    def __init__(self, path):
        super().__init__()
        self.elements = []
        self.feed(path.read_text(encoding="utf-8"))

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    @property
    def ids(self):
        return {attrs["id"] for _, attrs in self.elements if "id" in attrs}


@pytest.mark.parametrize("page", PAGES)
def test_public_page_links_and_resources_resolve_under_any_base_path(page):
    document = Document(SITE / page)
    for tag, attrs in document.elements:
        for attribute in ("href", "src"):
            if attribute not in attrs:
                continue
            link = attrs[attribute]
            assert link, (page, tag)
            url = urlsplit(link)
            if url.scheme or url.netloc:
                assert url.scheme == "https" and url.netloc, (page, link)
                assert tag == "a", "External resources must not load on page visits"
                continue
            assert not url.path.startswith("/"), "Support project and custom domain paths"
            destination = (SITE / unquote(url.path or page)).resolve()
            assert destination.is_relative_to(SITE.resolve()), (page, link)
            assert destination.is_file(), (page, link)
            if url.fragment:
                assert destination.suffix == ".html", (page, link)
                assert unquote(url.fragment) in Document(destination).ids, (page, link)


@pytest.mark.parametrize("page", PAGES)
def test_public_pages_offer_accessible_navigation_and_no_data_entry(page):
    document = Document(SITE / page)
    elements = document.elements
    assert any(tag == "html" and attrs.get("lang") == "pt-BR" for tag, attrs in elements)
    assert sum(tag == "main" for tag, _ in elements) == 1
    assert sum(tag == "h1" for tag, _ in elements) == 1
    assert sum(tag == "title" for tag, _ in elements) == 1
    assert any(tag == "meta" and attrs.get("name") == "viewport" for tag, attrs in elements)
    assert any(tag == "a" and attrs.get("href") == "#conteudo" for tag, attrs in elements)
    assert not {"script", "form", "input", "iframe", "object", "embed"}.intersection(
        tag for tag, _ in elements
    )
    for tag, attrs in elements:
        assert not any(name.startswith("on") for name in attrs), "No inline scripting"
        if tag == "img":
            assert attrs.get("alt"), "Illustrations need a readable description"
        if tag == "nav":
            assert attrs.get("aria-label"), "Navigation landmarks need distinct labels"
        assert int(attrs.get("tabindex", "0")) <= 0, "Preserve natural keyboard order"
    links = {attrs.get("href") for tag, attrs in elements if tag == "a"}
    assert {"privacidade.html", "termos.html"}.issubset(links)
    assert "https://github.com/R-Mascarenhas/RendaPerene/releases/latest" in links


def test_published_directory_contains_only_static_documents_and_local_assets():
    files = list(SITE.rglob("*"))
    assert files
    for path in files:
        assert not path.is_symlink(), f"Unexpected link in publication: {path}"
        if path.is_file():
            assert path.suffix in {".html", ".css", ".svg"}, f"Unexpected file: {path}"
            if path.suffix == ".css":
                content = path.read_text(encoding="utf-8").lower()
                assert "@import" not in content and "url(" not in content
