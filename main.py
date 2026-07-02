#!/usr/bin/env python3
"""OptiBot Clone - Main entry point.

Flexible run modes:
  scrape      - Scrape articles from Zendesk
  upload      - Upload existing markdown files to vector store
  full        - Scrape + Upload (default)
  cron        - Scrape articles + upload (for scheduled jobs, supports --limit --priority)

Usage:
  python main.py                    # Full pipeline (scrape + upload)
  python main.py scrape             # Scrape articles
  python main.py scrape --all      # Scrape ALL articles
  python main.py upload             # Upload existing files
  python main.py cron              # CI/CD scheduled job (scrape all + upload)
  python main.py                    # Start web server with scheduler
"""

import json
import sys
import time
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional

from flask import Flask, jsonify
from flask_apscheduler import APScheduler

from src.config import Config, SCHEDULE_CONFIG
from src.scraper import ArticleScraper
from src.uploader import OpenAIUploader
from src.logger_service import setup_daily_logging, get_logger


app = Flask(__name__)
app.config.from_object(SCHEDULE_CONFIG())
scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()

config = Config()
logger = setup_daily_logging(config.LOG_DIR)


def save_job_summary(summary: Dict[str, Any]):
    """Save job summary to JSON file for CI/CD artifacts."""
    summary_file = Path("job_summary.json")
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    return summary_file


def run_scraper(limit: int = None, priority_keywords: List[str] = None) -> bool:
    """Scrape articles from Zendesk API."""
    start_time = time.time()
    try:
        mode_str = f"Scraping {'ALL' if limit is None else limit} articles"
        if priority_keywords:
            mode_str += f" (priority: {', '.join(priority_keywords)})"
        
        logger.info("=" * 60)
        logger.info(f"[SCRAPE] {mode_str}")
        logger.info("=" * 60)

        scraper = ArticleScraper(config)
        
        if priority_keywords:
            kw_priority = {kw: i + 1 for i, kw in enumerate(priority_keywords)}
            kw_priority[""] = 999
            result = scraper.scrape_articles_priority(limit=limit, keywords_priority=kw_priority)
        else:
            result = scraper.scrape_articles(limit=limit)

        duration = time.time() - start_time
        logger.info("=" * 60)
        logger.info("[SCRAPE] Summary:")
        logger.info(f"  Added:     {len(result.added)}")
        logger.info(f"  Modified:  {len(result.modified)}")
        logger.info(f"  Skipped:   {len(result.skipped)}")
        logger.info(f"  Failed:    {result.failed}")
        logger.info(f"  Duration:  {duration:.1f}s")
        logger.info("=" * 60)

        summary = {
            "job": "scrape",
            "added": len(result.added),
            "modified": len(result.modified),
            "skipped": len(result.skipped),
            "failed": result.failed,
            "duration_seconds": round(duration, 1),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        save_job_summary(summary)

        return True

    except Exception as e:
        logger.error(f"[SCRAPE] Error: {e}")
        save_job_summary({
            "job": "scrape",
            "error": str(e),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        return False


def run_uploader(files: List[Path] = None) -> bool:
    """Upload markdown files to OpenAI vector store."""
    start_time = time.time()
    try:
        logger.info("=" * 60)
        logger.info("[UPLOAD] Starting...")
        logger.info("=" * 60)

        uploader = OpenAIUploader(config)
        articles_dir = Path(config.OUTPUT_DIR)

        if files is None:
            if not articles_dir.exists():
                logger.error(f"[UPLOAD] Directory not found: {articles_dir}")
                return False
            files = list(articles_dir.glob("*.md"))

        if not files:
            logger.warning("[UPLOAD] No markdown files found")
            save_job_summary({
                "job": "upload",
                "files_uploaded": 0,
                "chunks_embedded": 0,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            return True

        logger.info(f"[UPLOAD] Found {len(files)} files")

        result = uploader.upload_files(files)
        duration = time.time() - start_time

        logger.info("=" * 60)
        logger.info("[UPLOAD] Summary:")
        logger.info(f"  Files uploaded:  {result.files_uploaded}")
        logger.info(f"  Chunks embedded: {result.chunks_embedded}")
        logger.info(f"  Vector store:    {result.vector_store_id}")
        logger.info(f"  Duration:       {duration:.1f}s")
        logger.info("=" * 60)

        save_job_summary({
            "job": "upload",
            "files_uploaded": result.files_uploaded,
            "chunks_embedded": result.chunks_embedded,
            "vector_store_id": result.vector_store_id,
            "duration_seconds": round(duration, 1),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

        return True

    except Exception as e:
        logger.error(f"[UPLOAD] Error: {e}")
        save_job_summary({
            "job": "upload",
            "error": str(e),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        return False


def run_full(limit: int = None) -> bool:
    """Scrape + Upload pipeline."""
    start_time = time.time()
    try:
        mode_str = f"Scraping {'ALL' if limit is None else limit} articles"
        logger.info("=" * 60)
        logger.info(f"[FULL] {mode_str}")
        logger.info("=" * 60)

        scraper = ArticleScraper(config)
        result = scraper.scrape_articles(limit=limit)

        logger.info(f"[SCRAPE] Added: {len(result.added)}, Modified: {len(result.modified)}, Skipped: {len(result.skipped)}, Failed: {result.failed}")

        files = scraper.get_files_to_upload()
        upload_result = None
        if files:
            logger.info(f"[UPLOAD] Uploading {len(files)} files...")
            uploader = OpenAIUploader(config)
            upload_result = uploader.upload_files(files)
            logger.info(f"[UPLOAD] Done. Files: {upload_result.files_uploaded}, Chunks: {upload_result.chunks_embedded}")
        else:
            logger.info("[UPLOAD] No new/modified files to upload")

        duration = time.time() - start_time
        logger.info("=" * 60)
        logger.info("[FULL] Complete!")
        logger.info(f"  Duration: {duration:.1f}s")
        logger.info("=" * 60)

        save_job_summary({
            "job": "full",
            "scraped": {
                "added": len(result.added),
                "modified": len(result.modified),
                "skipped": len(result.skipped),
                "failed": result.failed,
            },
            "uploaded": {
                "files_uploaded": upload_result.files_uploaded if upload_result else 0,
                "chunks_embedded": upload_result.chunks_embedded if upload_result else 0,
            } if upload_result else {"files_uploaded": 0, "chunks_embedded": 0},
            "duration_seconds": round(duration, 1),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

        return True

    except Exception as e:
        logger.error(f"[FULL] Error: {e}")
        save_job_summary({
            "job": "full",
            "error": str(e),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        return False


def run_cron(limit: Optional[int] = None, priority_keywords: Optional[List[str]] = None) -> bool:
    """Scheduled job: Scrape articles + upload delta.
    
    Args:
        limit: Number of articles to scrape (None = all)
        priority_keywords: Keywords to prioritize
    """
    start_time = time.time()
    try:
        logger.info("=" * 60)
        logger.info("[CRON] Daily sync job started")
        logger.info("=" * 60)

        scraper = ArticleScraper(config)
        
        # Use priority method if keywords provided, otherwise use standard
        if priority_keywords:
            # Build priority dict: youtube=1, google=2, etc.
            keywords_priority = {kw: i+1 for i, kw in enumerate(priority_keywords)}
            keywords_priority[""] = 100  # default priority
            result = scraper.scrape_articles_priority(limit=limit, keywords_priority=keywords_priority)
        else:
            result = scraper.scrape_articles(limit=limit)

        logger.info(f"[CRON] Scraped - Added: {len(result.added)}, Modified: {len(result.modified)}, Skipped: {len(result.skipped)}, Failed: {result.failed}")

        files = scraper.get_files_to_upload()
        upload_result = None
        if files:
            logger.info(f"[CRON] Uploading {len(files)} delta files...")
            uploader = OpenAIUploader(config)
            upload_result = uploader.upload_files(files)
            logger.info(f"[CRON] Uploaded - Files: {upload_result.files_uploaded}, Chunks: {upload_result.chunks_embedded}")
        else:
            logger.info("[CRON] No delta to upload")

        duration = time.time() - start_time
        logger.info("=" * 60)
        logger.info("[CRON] Daily sync complete!")
        logger.info(f"  Added:     {len(result.added)}")
        logger.info(f"  Modified:  {len(result.modified)}")
        logger.info(f"  Skipped:   {len(result.skipped)}")
        logger.info(f"  Failed:    {result.failed}")
        logger.info(f"  Uploaded:  {upload_result.files_uploaded if upload_result else 0} files, {upload_result.chunks_embedded if upload_result else 0} chunks")
        logger.info(f"  Duration:  {duration:.1f}s")
        logger.info("=" * 60)

        save_job_summary({
            "job": "cron",
            "scraped": {
                "added": len(result.added),
                "modified": len(result.modified),
                "skipped": len(result.skipped),
                "failed": result.failed,
            },
            "uploaded": {
                "files_uploaded": upload_result.files_uploaded if upload_result else 0,
                "chunks_embedded": upload_result.chunks_embedded if upload_result else 0,
            } if upload_result else {"files_uploaded": 0, "chunks_embedded": 0},
            "duration_seconds": round(duration, 1),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

        return True

    except Exception as e:
        logger.error(f"[CRON] Error: {e}")
        save_job_summary({
            "job": "cron",
            "error": str(e),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        return False


@scheduler.task("cron", id="daily_scrape_job", hour=config.SCHEDULE_HOUR, minute=config.SCHEDULE_MINUTE)
def daily_job():
    """Daily scheduled job."""
    run_full()


# --- Web Endpoints ---

@app.route("/")
def home():
    return "OptiBot Clone is running!"

@app.route("/health")
def health():
    return jsonify({"status": "healthy", "service": "optibot-clone"})

@app.route("/scrape")
def scrape_endpoint():
    success = run_scraper()
    return jsonify({"success": success})

@app.route("/upload")
def upload_endpoint():
    success = run_uploader()
    return jsonify({"success": success})

@app.route("/run")
def run_endpoint():
    success = run_full()
    return jsonify({"success": success})


# --- CLI ---

def main():
    parser = argparse.ArgumentParser(
        description="OptiBot Clone - AI Support Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Run Modes:
  scrape   Scrape articles from Zendesk
  upload   Upload existing files to vector store
  full     Scrape + Upload (default)
  cron     Scrape ALL + upload (for scheduled jobs/CI-CD)

Options:
  --all              Scrape ALL articles (no limit)
  --limit N          Scrape N articles
  --priority KW,...  Prioritize articles with keyword (e.g., --priority youtube,google)

Examples:
  python main.py scrape --all                  # Scrape all articles
  python main.py scrape --limit 30             # Scrape 30 articles
  python main.py scrape --limit 30 --priority youtube  # Prioritize youtube articles first
  python main.py upload                        # Upload existing files
  python main.py cron                          # CI/CD scheduled job (scrape all + upload)
  python main.py                               # Start web server
        """
    )

    parser.add_argument(
        "mode",
        choices=["scrape", "upload", "full", "cron"],
        default="full",
        nargs="?",
        help="Run mode (default: full)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Scrape ALL articles (no limit)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Number of articles to scrape",
    )
    parser.add_argument(
        "--priority",
        type=str,
        default=None,
        help="Priority keywords (comma-separated, e.g., 'youtube,google')",
    )

    args = parser.parse_args()

    # Parse priority keywords (default: youtube for cron)
    if args.mode == "cron":
        priority_keywords = args.priority.split(",") if args.priority else ["youtube"]
    else:
        priority_keywords = [kw.strip().lower() for kw in args.priority.split(",")] if args.priority else None
    
    # Determine limit (default: 30 for cron, None for others)
    limit = None
    if args.all:
        limit = None
    elif args.limit:
        limit = args.limit
    elif args.mode == "scrape":
        limit = config.COUNT_ARTICLES
    elif args.mode == "cron":
        limit = 30  # Default for cron: 30 articles

    # Run based on mode
    if args.mode == "scrape":
        success = run_scraper(limit=limit, priority_keywords=priority_keywords)
    elif args.mode == "upload":
        success = run_uploader()
    elif args.mode == "cron":
        success = run_cron(limit=limit, priority_keywords=priority_keywords)
    else:
        success = run_full(limit=limit)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
