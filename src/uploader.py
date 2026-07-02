"""OpenAI Vector Store uploader for OptiBot Clone.

Uploads Markdown files to OpenAI Vector Store via API for use with
AI assistants. Supports batch uploads and delta uploads.
"""

import time
from pathlib import Path
from typing import List, Optional, Dict
from dataclasses import dataclass

from openai import OpenAI
from openai.types import VectorStore
from openai.types.vector_stores import VectorStoreFile

from .logger_service import get_logger
from .config import Config


@dataclass
class UploadResult:
    """Result of upload operation."""
    files_uploaded: int
    chunks_embedded: int
    file_ids: List[str]
    vector_store_id: str


class OpenAIUploader:
    """Handles file uploads to OpenAI Vector Store."""

    MAX_FILES_PER_VECTOR_STORE = 100

    def __init__(self, config: Optional[Config] = None):
        """Initialize uploader with OpenAI client."""
        self.config = config or Config()
        self.logger = get_logger("uploader", "production")

        if not self.config.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is required")

        self.client = OpenAI(api_key=self.config.OPENAI_API_KEY)
        self.vector_store_id: Optional[str] = None

    def create_vector_store(self, name: str = "optibot-knowledge-base") -> VectorStore:
        """Create or get existing vector store."""
        existing_stores = self.client.vector_stores.list()

        for store in existing_stores.data:
            if store.name == name:
                self.logger.info(f"Using existing vector store: {name} ({store.id})")
                self.vector_store_id = store.id
                return store

        vector_store = self.client.vector_stores.create(name=name)
        self.vector_store_id = vector_store.id
        self.logger.info(f"Created new vector store: {name} ({vector_store.id})")
        return vector_store

    def upload_file(self, file_path: Path) -> Optional[str]:
        """Upload single file to OpenAI and return file ID."""
        try:
            with open(file_path, "rb") as file:
                response = self.client.files.create(
                    file=file,
                    purpose="assistants",
                )
                self.logger.debug(f"Uploaded file: {file_path.name} -> {response.id}")
                return response.id
        except Exception as e:
            self.logger.error(f"Error uploading {file_path}: {e}")
            return None

    def upload_files_batch(
        self, file_paths: List[Path], vector_store_id: str, batch_num: int = 1
    ) -> List[str]:
        """Upload multiple files and attach to vector store.
        
        Chunking Strategy:
        - Uses 'auto' for dynamic chunking based on content structure
        - OpenAI intelligently splits by headers, paragraphs, code blocks
        - Optimal for technical docs with mixed content (headings, lists, code)
        """
        file_ids = []

        for file_path in file_paths:
            file_id = self.upload_file(file_path)
            if file_id:
                file_ids.append(file_id)

        if not file_ids:
            return []

        self.logger.info(f"Batch {batch_num}: Attaching {len(file_ids)} files to vector store")

        # OpenAI auto chunking - no custom strategy needed
        chunking_strategy = {"type": "auto"}

        batch = self.client.vector_stores.file_batches.create(
            vector_store_id=vector_store_id,
            file_ids=file_ids,
            chunking_strategy=chunking_strategy,
        )

        self.logger.info(f"Batch {batch_num}: File batch created, ID: {batch.id}")

        self._wait_for_batch_completion(batch.id, vector_store_id)

        return file_ids

    def _wait_for_batch_completion(
        self, batch_id: str, vector_store_id: str, timeout: int = 300
    ) -> Dict:
        """Wait for file batch processing to complete."""
        start_time = time.time()

        while time.time() - start_time < timeout:
            batch = self.client.vector_stores.file_batches.retrieve(
                batch_id=batch_id,
                vector_store_id=vector_store_id,
            )

            status = batch.status
            self.logger.debug(f"Batch status: {status}")

            if status == "completed":
                self.logger.info("Batch processing completed")
                return {"status": "completed", "batch": batch}
            elif status == "failed":
                self.logger.error(f"Batch processing failed: {batch}")
                return {"status": "failed", "batch": batch}

            time.sleep(5)

        self.logger.warning("Batch processing timed out")
        return {"status": "timeout"}

    def get_embedding_count(self, vector_store_id: str) -> int:
        """Get count of embedded files in vector store."""
        files = self.client.vector_stores.files.list(vector_store_id=vector_store_id)
        return len(list(files.data))

    def upload_files(self, file_paths: List[Path]) -> UploadResult:
        """Upload all files to vector store with batching."""
        if not file_paths:
            self.logger.info("No files to upload")
            return UploadResult(
                files_uploaded=0,
                chunks_embedded=0,
                file_ids=[],
                vector_store_id="",
            )

        self.logger.info(f"Starting upload of {len(file_paths)} files...")

        vector_store = self.create_vector_store()
        all_file_ids = []

        batches = [
            file_paths[i : i + self.MAX_FILES_PER_VECTOR_STORE]
            for i in range(0, len(file_paths), self.MAX_FILES_PER_VECTOR_STORE)
        ]

        for i, batch in enumerate(batches, 1):
            batch_ids = self.upload_files_batch(batch, vector_store.id, i)
            all_file_ids.extend(batch_ids)

        total_chunks = self.get_embedding_count(vector_store.id)

        self.logger.info(
            f"Upload complete - Files: {len(all_file_ids)}, "
            f"Chunks embedded: {total_chunks}"
        )

        return UploadResult(
            files_uploaded=len(all_file_ids),
            chunks_embedded=total_chunks,
            file_ids=all_file_ids,
            vector_store_id=vector_store.id,
        )

    def handle_delta(self, new_files: List[Path], modified_files: List[Path]) -> UploadResult:
        """Handle delta upload - only new and modified files."""
        files_to_upload = new_files + modified_files
        self.logger.info(
            f"Delta upload: {len(new_files)} new, {len(modified_files)} modified"
        )
        return self.upload_files(files_to_upload)

    def delete_all_files(self):
        """Delete all files from OpenAI (use with caution)."""
        files = self.client.files.list()
        for file in files.data:
            self.client.files.delete(file_id=file.id)
            self.logger.info(f"Deleted file: {file.id}")
