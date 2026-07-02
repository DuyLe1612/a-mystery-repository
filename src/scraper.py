"""Article scraper for OptiBot Clone.

Scrapes articles from Zendesk Help Center public API and converts them to Markdown format.
No API key required - uses the public-facing Zendesk Help Center API.
Supports delta detection to identify new, modified, and unchanged articles.
"""

import hashlib
import time
import json
import re
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime

import requests
import html2text
from bs4 import BeautifulSoup, NavigableString
from slugify import slugify

from .logger_service import get_logger
from .config import Config


@dataclass
class ArticleResult:
    """Result of scraping operation."""
    added: List[Path]
    modified: List[Path]
    skipped: List[Path]
    failed: int = 0


@dataclass
class PriorityScrapeConfig:
    """Configuration for priority-based scraping."""
    priorities: Dict[str, int] = None  # keyword -> priority (lower = higher priority)
    limit: int = 30  # total articles to scrape

    def __post_init__(self):
        if self.priorities is None:
            # Default: youtube first, then everything else
            self.priorities = {
                "youtube": 1,
                "": 100,  # fallback for articles without keywords
            }


class ArticleScraper:
    """Scrapes articles from Zendesk public API and converts to Markdown."""

    def __init__(self, config: Optional[Config] = None):
        """Initialize the scraper with configuration."""
        self.config = config or Config()
        self.logger = get_logger("scraper", "production")

        self.base_url = f"https://support.optisigns.com/api/v2/help_center"
        self.output_dir = self._setup_output_directory()
        self.html_converter = self._setup_html_converter()
        self.metadata_file = self.output_dir / "metadata.json"

        self.files: Dict[str, List[Path]] = {
            "added": [],
            "modified": [],
            "skipped": [],
        }
        self.failed_count: int = 0

    def _setup_output_directory(self) -> Path:
        """Create output directory if it doesn't exist."""
        output_dir = Path(self.config.OUTPUT_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def _setup_html_converter(self) -> html2text.HTML2Text:
        """Configure HTML to Markdown converter."""
        converter = html2text.HTML2Text()
        converter.body_width = 0
        converter.unicode_snob = True
        converter.ignore_links = False
        converter.ignore_images = False
        converter.ignore_emphasis = False
        converter.ignore_tables = False
        converter.mark_code = True
        return converter

    def load_metadata(self) -> Dict:
        """Load existing articles metadata."""
        if self.metadata_file.exists():
            with open(self.metadata_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def save_metadata(self, metadata: Dict):
        """Save articles metadata."""
        with open(self.metadata_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

    def get_article_hash(self, content: str) -> str:
        """Generate MD5 hash for article content."""
        return hashlib.md5(content.encode("utf-8")).hexdigest()

    def fetch_articles_list(self, per_page: int = 100) -> List[Dict]:
        """Fetch list of articles from public Zendesk API."""
        articles = []
        page = 1

        self.logger.info("Fetching articles list from Zendesk public API...")

        while True:
            try:
                url = f"{self.base_url}/en-us/articles.json?page={page}&per_page={per_page}"
                response = requests.get(url, timeout=30)

                if response.status_code != 200:
                    self.logger.error(f"API error: {response.status_code}")
                    break

                data = response.json()
                page_articles = data.get("articles", [])

                if not page_articles:
                    break

                articles.extend(page_articles)
                self.logger.info(f"Page {page}: fetched {len(page_articles)} articles")

                if not data.get("next_page"):
                    break

                page += 1
                time.sleep(0.3)

            except Exception as e:
                self.logger.error(f"Error fetching page {page}: {e}")
                break

        self.logger.info(f"Total articles found: {len(articles)}")
        return articles

    def fetch_article_content(self, article_id: int) -> Optional[Dict]:
        """Fetch single article content from public Zendesk API."""
        try:
            url = f"{self.base_url}/en-us/articles/{article_id}.json"
            response = requests.get(url, timeout=30)

            if response.status_code == 200:
                return response.json().get("article")
            else:
                self.logger.warning(f"Failed to fetch article {article_id}: {response.status_code}")
                return None

        except Exception as e:
            self.logger.error(f"Error fetching article {article_id}: {e}")
            return None

    def remove_unwanted_elements(self, soup: BeautifulSoup) -> BeautifulSoup:
        """Remove nav, ads, and other unwanted elements from HTML."""
        unwanted_selectors = [
            "nav", "header", "footer", "aside",
            "script", "style", "noscript", "iframe",
            "meta", "link", "svg", "form", "button",
            ".nav", ".navbar", ".navigation", ".menu",
            ".sidebar", ".ad", ".ads", ".advertisement",
            ".breadcrumb", ".breadcrumbs", ".toc",
            ".related-articles", ".related-posts",
            ".share-buttons", ".social-share",
            "[class*='nav']", "[class*='menu']",
            "[class*='sidebar']", "[class*='footer']",
            "[class*='header']", "[class*='ad']",
            "[id*='nav']", "[id*='menu']",
            "[id*='sidebar']", "[id*='footer']",
            "[id*='header']", "[id*='ad']",
            ".article-footer", ".article-header",
            ".comments", ".comment-section",
            ".popup", ".modal", ".overlay",
        ]

        for selector in unwanted_selectors:
            for element in soup.select(selector):
                element.decompose()

        for tag in soup.find_all(["script", "style", "noscript", "iframe", "meta", "link", "svg"]):
            tag.decompose()

        return soup

    def clean_html(self, html: str) -> str:
        """Clean HTML, removing nav/ads while preserving content structure."""
        soup = BeautifulSoup(html, "html.parser")
        soup = self.remove_unwanted_elements(soup)

        for text in soup.find_all(text=True):
            if isinstance(text, NavigableString):
                stripped = text.strip()
                if stripped:
                    text.replace_with(stripped + " ")
                else:
                    text.replace_with(" ")

        result = str(soup)
        result = re.sub(r" +", " ", result)
        return result

    def clean_markdown(self, markdown: str) -> str:
        """Clean up markdown while preserving structure."""
        lines = []
        prev_empty = False

        for line in markdown.split("\n"):
            stripped = line.strip()

            if not stripped:
                if not prev_empty:
                    lines.append("")
                prev_empty = True
            else:
                lines.append(line)
                prev_empty = False

        cleaned = "\n".join(lines).strip()

        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

        return cleaned

    def convert_to_markdown(self, html_content: str, title: str, article_url: str) -> str:
        """Convert HTML to Markdown preserving structure.
        
        Format: Content first, Article URL at END for citation support.
        """
        cleaned_html = self.clean_html(html_content)
        markdown = self.html_converter.handle(cleaned_html)
        markdown = self.clean_markdown(markdown)

        content = f"""# {title}

{markdown}

---

Article URL: {article_url}
"""
        return content

    def scrape_article(self, article_info: Dict) -> Optional[Dict]:
        """Scrape a single article."""
        article_id = article_info["id"]

        article = self.fetch_article_content(article_id)
        if not article:
            return None

        html_body = article.get("body", "")
        article_url = article.get("html_url", "")

        if not html_body:
            return None

        markdown = self.convert_to_markdown(html_body, article.get("title", "Untitled"), article_url)

        if not markdown or len(markdown) < 50:
            return None

        return {
            "markdown": markdown,
            "hash": self.get_article_hash(markdown),
            "url": article_url,
            "title": article.get("title", "Untitled"),
            "updated_at": article.get("updated_at", ""),
            "id": article_id,
            "scraped_at": datetime.now().isoformat(),
        }

    def generate_slug(self, title: str) -> str:
        """Generate URL-friendly slug from title."""
        return slugify(title, max_length=100, word_boundary=True, save_order=True)

    def get_existing_slug(self, article_id: str, metadata: Dict) -> Optional[str]:
        """Get existing slug from metadata for backward compatibility."""
        if article_id in metadata and "slug" in metadata[article_id]:
            return metadata[article_id]["slug"]
        return None

    def save_article_to_file(self, article_data: Dict, filename: str) -> Path:
        """Save article to file."""
        filepath = self.output_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(article_data["markdown"])
        return filepath

    def scrape_articles(self, limit: Optional[int] = None) -> ArticleResult:
        """Scrape articles from Zendesk and return result summary.
        
        Args:
            limit: Maximum number of articles to scrape. None = all articles.
        """
        all_articles = self.fetch_articles_list()
        if not all_articles:
            self.logger.error("No articles found!")
            return ArticleResult(added=[], modified=[], skipped=[], failed=0)

        articles_to_scrape = all_articles[:limit] if limit else all_articles
        self.logger.info(f"Starting to scrape {len(articles_to_scrape)} articles...")
        self.logger.info(f"Processing {len(articles_to_scrape)} articles...")

        metadata = self.load_metadata()

        for i, article_info in enumerate(articles_to_scrape, 1):
            title = article_info.get("title", "Untitled")[:60]
            article_id = str(article_info["id"])

            self.logger.info(f"[{i}/{len(articles_to_scrape)}] {title}...")

            article_data = self.scrape_article(article_info)

            if not article_data:
                self.logger.warning(f"[{i}/{len(articles_to_scrape)}] Failed to scrape")
                self.failed_count += 1
                time.sleep(0.3)
                continue

            slug = self.generate_slug(article_data["title"])
            existing_slug = self.get_existing_slug(article_id, metadata)
            if existing_slug:
                slug = existing_slug

            filename = f"{slug}.md"

            if article_id in metadata:
                if metadata[article_id]["hash"] != article_data["hash"]:
                    self.logger.info(f"  -> Updated")
                    self.files["modified"].append(self.save_article_to_file(article_data, filename))
                    metadata[article_id].update({
                        "hash": article_data["hash"],
                        "slug": slug,
                        "last_updated": article_data["scraped_at"],
                    })
                else:
                    self.logger.info(f"  -> Unchanged (skipped)")
                    self.files["skipped"].append(Path(filename))
            else:
                self.logger.info(f"  -> Added")
                self.files["added"].append(self.save_article_to_file(article_data, filename))
                metadata[article_id] = {
                    "hash": article_data["hash"],
                    "slug": slug,
                    "url": article_data["url"],
                    "title": article_data["title"],
                    "filename": filename,
                    "last_updated": article_data["scraped_at"],
                }

            time.sleep(0.3)

        self.save_metadata(metadata)

        self.logger.info(
            f"Scraping complete - Added: {len(self.files['added'])}, "
            f"Modified: {len(self.files['modified'])}, "
            f"Skipped: {len(self.files['skipped'])}, "
            f"Failed: {self.failed_count}"
        )

        return ArticleResult(
            added=self.files["added"],
            modified=self.files["modified"],
            skipped=self.files["skipped"],
            failed=self.failed_count,
        )

    def get_files_to_upload(self) -> List[Path]:
        """Get list of files that need to be uploaded (added + modified)."""
        return self.files["added"] + self.files["modified"]

    def get_article_priority(self, title: str, keywords_priority: Dict[str, int]) -> int:
        """Get priority score for an article based on keywords in title.
        
        Lower score = higher priority (scraped first)
        """
        title_lower = title.lower()
        best_priority = float('inf')
        
        for keyword, priority in keywords_priority.items():
            if keyword and keyword.lower() in title_lower:
                if priority < best_priority:
                    best_priority = priority
        
        return best_priority if best_priority != float('inf') else 999

    def scrape_articles_priority(
        self, 
        limit: int = 30, 
        keywords_priority: Dict[str, int] = None
    ) -> ArticleResult:
        """Scrape articles with priority ordering.
        
        1. First scrapes articles matching high-priority keywords (e.g., "youtube")
        2. Then fills remaining slots from other articles
        
        Args:
            limit: Total number of articles to scrape
            keywords_priority: Dict of {keyword: priority} where lower = higher priority
        """
        if keywords_priority is None:
            keywords_priority = {"youtube": 1, "": 100}
        
        all_articles = self.fetch_articles_list()
        if not all_articles:
            self.logger.error("No articles found!")
            return ArticleResult(added=[], modified=[], skipped=[], failed=0)

        self.logger.info(f"Total articles available: {len(all_articles)}")
        
        # Sort by priority
        def sort_key(article):
            title = article.get("title", "")
            return self.get_article_priority(title, keywords_priority)
        
        sorted_articles = sorted(all_articles, key=sort_key)
        articles_to_scrape = sorted_articles[:limit]
        
        # Log priority order
        self.logger.info("Priority order (first 10):")
        for i, art in enumerate(articles_to_scrape[:10], 1):
            self.logger.info(f"  {i}. {art.get('title', 'Untitled')[:50]}")
        
        self.logger.info(f"Starting to scrape {len(articles_to_scrape)} articles with priority...")
        
        metadata = self.load_metadata()

        for i, article_info in enumerate(articles_to_scrape, 1):
            title = article_info.get("title", "Untitled")[:60]
            article_id = str(article_info["id"])

            self.logger.info(f"[{i}/{len(articles_to_scrape)}] {title}...")

            article_data = self.scrape_article(article_info)

            if not article_data:
                self.logger.warning(f"[{i}/{len(articles_to_scrape)}] Failed to scrape")
                self.failed_count += 1
                time.sleep(0.3)
                continue

            slug = self.generate_slug(article_data["title"])
            existing_slug = self.get_existing_slug(article_id, metadata)
            if existing_slug:
                slug = existing_slug

            filename = f"{slug}.md"

            if article_id in metadata:
                if metadata[article_id]["hash"] != article_data["hash"]:
                    self.logger.info(f"  -> Updated")
                    self.files["modified"].append(self.save_article_to_file(article_data, filename))
                    metadata[article_id].update({
                        "hash": article_data["hash"],
                        "slug": slug,
                        "last_updated": article_data["scraped_at"],
                    })
                else:
                    self.logger.info(f"  -> Unchanged (skipped)")
                    self.files["skipped"].append(Path(filename))
            else:
                self.logger.info(f"  -> Added")
                self.files["added"].append(self.save_article_to_file(article_data, filename))
                metadata[article_id] = {
                    "hash": article_data["hash"],
                    "slug": slug,
                    "url": article_data["url"],
                    "title": article_data["title"],
                    "filename": filename,
                    "last_updated": article_data["scraped_at"],
                }

            time.sleep(0.3)

        self.save_metadata(metadata)

        self.logger.info(
            f"Scraping complete - Added: {len(self.files['added'])}, "
            f"Modified: {len(self.files['modified'])}, "
            f"Skipped: {len(self.files['skipped'])}, "
            f"Failed: {self.failed_count}"
        )

        return ArticleResult(
            added=self.files["added"],
            modified=self.files["modified"],
            skipped=self.files["skipped"],
            failed=self.failed_count,
        )

    def get_stats(self) -> Dict:
        """Get scraping statistics."""
        return {
            "added": len(self.files["added"]),
            "modified": len(self.files["modified"]),
            "skipped": len(self.files["skipped"]),
            "failed": self.failed_count,
        }
