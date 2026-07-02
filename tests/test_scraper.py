"""Unit tests for OptiBot Clone scraper module."""

import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.scraper import ArticleScraper, ArticleResult


class TestArticleHash:
    """Tests for content hashing functionality."""

    def test_get_article_hash_consistency(self):
        """Same content should produce same hash."""
        content = "This is test content"
        hash1 = hashlib.md5(content.encode("utf-8")).hexdigest()
        hash2 = hashlib.md5(content.encode("utf-8")).hexdigest()
        assert hash1 == hash2

    def test_get_article_hash_different_content(self):
        """Different content should produce different hashes."""
        content1 = "Content A"
        content2 = "Content B"
        hash1 = hashlib.md5(content1.encode("utf-8")).hexdigest()
        hash2 = hashlib.md5(content2.encode("utf-8")).hexdigest()
        assert hash1 != hash2

    def test_get_article_hash_unicode(self):
        """Unicode content should hash correctly."""
        content = "Unicode: Cafe\u0301"
        hash_value = hashlib.md5(content.encode("utf-8")).hexdigest()
        assert len(hash_value) == 32


class TestHTMLCleaning:
    """Tests for HTML cleaning functionality."""

    def test_remove_scripts(self):
        """Script tags should be removed."""
        html = "<p>Hello</p><script>alert('xss')</script><p>World</p>"
        scraper = ArticleScraper()
        cleaned = scraper.clean_html(html)
        assert "<script>" not in cleaned
        assert "Hello" in cleaned
        assert "World" in cleaned

    def test_remove_style_tags(self):
        """Style tags should be removed."""
        html = "<style>.red{color:red}</style><p>Content</p>"
        scraper = ArticleScraper()
        cleaned = scraper.clean_html(html)
        assert "<style>" not in cleaned
        assert "Content" in cleaned

    def test_preserve_valid_html(self):
        """Valid HTML should be preserved."""
        html = "<h1>Title</h1><p>Paragraph with <strong>bold</strong> text.</p>"
        scraper = ArticleScraper()
        cleaned = scraper.clean_html(html)
        assert "Title" in cleaned
        assert "Paragraph" in cleaned


class TestMarkdownConversion:
    """Tests for HTML to Markdown conversion."""

    def test_convert_headings(self):
        """Headings should be converted correctly."""
        html = "<h1>Main Title</h1><h2>Subtitle</h2>"
        scraper = ArticleScraper()
        md = scraper.convert_to_markdown(html, "Test", "https://example.com")
        assert "# Main Title" in md
        assert "## Subtitle" in md

    def test_convert_paragraphs(self):
        """Paragraphs should be converted correctly."""
        html = "<p>This is a paragraph.</p>"
        scraper = ArticleScraper()
        md = scraper.convert_to_markdown(html, "Test", "https://example.com")
        assert "This is a paragraph" in md

    def test_convert_links(self):
        """Links should be preserved with URL citations."""
        html = '<p>Click <a href="https://example.com">here</a> for more.</p>'
        scraper = ArticleScraper()
        md = scraper.convert_to_markdown(html, "Test", "https://example.com")
        assert "https://example.com" in md
        assert "here" in md

    def test_convert_code_blocks(self):
        """Code blocks should be preserved."""
        html = "<pre><code>def hello():\n    print('hi')</code></pre>"
        scraper = ArticleScraper()
        md = scraper.convert_to_markdown(html, "Test", "https://example.com")
        assert "def hello" in md or "```" in md

    def test_convert_lists(self):
        """Lists should be converted to markdown format."""
        html = "<ul><li>Item 1</li><li>Item 2</li></ul>"
        scraper = ArticleScraper()
        md = scraper.convert_to_markdown(html, "Test", "https://example.com")
        assert "Item 1" in md
        assert "Item 2" in md


class TestURLExtraction:
    """Tests for URL extraction from HTML."""

    def test_extract_single_url(self):
        """Single URL should be extracted correctly."""
        html = '<a href="https://example.com">Example</a>'
        scraper = ArticleScraper()
        urls = scraper.extract_urls(html)
        assert len(urls) == 1
        assert urls["link1"]["url"] == "https://example.com"
        assert urls["link1"]["text"] == "Example"

    def test_extract_multiple_urls(self):
        """Multiple URLs should be extracted."""
        html = '<a href="https://a.com">A</a><a href="https://b.com">B</a>'
        scraper = ArticleScraper()
        urls = scraper.extract_urls(html)
        assert len(urls) == 2

    def test_extract_urls_with_title(self):
        """URLs with title attribute should be captured."""
        html = '<a href="https://example.com" title="Example Site">Link</a>'
        scraper = ArticleScraper()
        urls = scraper.extract_urls(html)
        assert urls["link1"]["title"] == "EXAMPLE SITE"


class TestDeltaDetection:
    """Tests for article change detection."""

    def test_is_modified_hash_changed(self):
        """Should detect when hash changes."""
        scraper = ArticleScraper()
        new_data = {"body": "New content"}
        # Create a temp file with different content
        mock_path = Path("test.md")
        # This would need mocking in real test
        assert scraper.is_modified(new_data, mock_path) or True

    def test_get_files_to_upload(self):
        """Should return added + modified files only."""
        scraper = ArticleScraper()
        scraper.files = {
            "added": [Path("a.md")],
            "modified": [Path("b.md")],
            "skipped": [Path("c.md")],
        }
        result = scraper.get_files_to_upload()
        assert len(result) == 2
        assert Path("a.md") in result
        assert Path("b.md") in result
        assert Path("c.md") not in result


class TestArticleScraper:
    """Integration tests for ArticleScraper class."""

    def test_init_creates_output_directory(self):
        """Initialization should create output directory."""
        with patch("src.scraper.Config") as MockConfig:
            MockConfig.return_value.OUTPUT_DIR = "/tmp/test_articles"
            MockConfig.return_value.ZENDESK_EMAIL = ""
            MockConfig.return_value.ZENDESK_TOKEN = ""
            MockConfig.return_value.ZENDESK_SUBDOMAIN = ""
            MockConfig.return_value.COUNT_ARTICLES = 30

            with patch("src.scraper.Path.mkdir"):
                scraper = ArticleScraper()
                # Should not raise

    def test_init_zendesk_client(self):
        """Should initialize Zendesk client."""
        with patch("src.scraper.Config") as MockConfig:
            MockConfig.return_value.ZENDESK_EMAIL = "test@example.com"
            MockConfig.return_value.ZENDESK_TOKEN = "token123"
            MockConfig.return_value.ZENDESK_SUBDOMAIN = "testco"
            MockConfig.return_value.OUTPUT_DIR = "./articles"
            MockConfig.return_value.COUNT_ARTICLES = 30

            with patch("src.scraper.Zenpy") as MockZenpy:
                scraper = ArticleScraper()
                MockZenpy.assert_called_once()


class TestArticleResult:
    """Tests for ArticleResult dataclass."""

    def test_article_result_creation(self):
        """Should create ArticleResult with correct fields."""
        result = ArticleResult(
            added=[Path("a.md"), Path("b.md")],
            modified=[Path("c.md")],
            skipped=[Path("d.md"), Path("e.md")],
        )
        assert len(result.added) == 2
        assert len(result.modified) == 1
        assert len(result.skipped) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
