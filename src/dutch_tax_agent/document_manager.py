"""Document lifecycle management: hashing, deduplication, removal."""

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dutch_tax_agent.schemas.documents import ExtractionResult
from dutch_tax_agent.schemas.tax_entities import Box1Income, Box3Asset

logger = logging.getLogger(__name__)


class DocumentManager:
    """Manages document lifecycle: hashing, deduplication, removal, and recalculation."""
    
    def hash_pdf(self, pdf_path: Path) -> str:
        """Generate SHA256 hash of PDF file.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            SHA256 hash as hex string
        """
        sha256_hash = hashlib.sha256()
        
        with open(pdf_path, "rb") as f:
            # Read file in chunks to handle large PDFs
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        
        return sha256_hash.hexdigest()
    
    def find_new_documents(
        self, 
        pdf_paths: list[Path], 
        processed_docs: list[dict]
    ) -> list[Path]:
        """Filter out already-processed documents based on hash and ID.
        
        Args:
            pdf_paths: List of PDF file paths to check
            processed_docs: List of already processed document metadata
            
        Returns:
            List of new (unprocessed) PDF paths
        """
        # Extract hashes and IDs of already processed documents
        processed_hashes = {doc["hash"] for doc in processed_docs}
        processed_ids = {doc["id"] for doc in processed_docs}
        
        new_documents = []
        for pdf_path in pdf_paths:
            doc_hash = self.hash_pdf(pdf_path)
            doc_id = doc_hash[:12]  # Same ID generation logic as create_document_metadata
            
            # Check both hash and ID to prevent duplicates
            if doc_hash not in processed_hashes and doc_id not in processed_ids:
                new_documents.append(pdf_path)
                logger.info(f"New document found: {pdf_path.name} (hash: {doc_hash[:12]})")
            else:
                if doc_hash in processed_hashes:
                    logger.info(f"Skipping already processed document (by hash): {pdf_path.name}")
                elif doc_id in processed_ids:
                    logger.info(f"Skipping already processed document (by ID): {pdf_path.name}")
        
        return new_documents
    
    def remove_documents(
        self,
        processed_docs: list[dict],
        doc_ids: Optional[list[str]] = None,
        filenames: Optional[list[str]] = None,
        remove_all: bool = False
    ) -> tuple[list[dict], list[str]]:
        """Remove documents from processed list.
        
        Args:
            processed_docs: List of processed document metadata
            doc_ids: Optional list of document IDs to remove
            filenames: Optional list of filenames to remove
            remove_all: If True, remove all documents
            
        Returns:
            Tuple of (updated_docs_list, removed_doc_ids)
        """
        if remove_all:
            removed_ids = [doc["id"] for doc in processed_docs]
            logger.info(f"Removing all {len(processed_docs)} documents")
            return [], removed_ids
        
        # Build set of document IDs to remove
        ids_to_remove = set()
        
        if doc_ids:
            ids_to_remove.update(doc_ids)
        
        if filenames:
            # Find document IDs by filename
            for doc in processed_docs:
                if doc["filename"] in filenames:
                    ids_to_remove.add(doc["id"])
        
        # Filter out documents
        updated_docs = [doc for doc in processed_docs if doc["id"] not in ids_to_remove]
        removed_ids = list(ids_to_remove)
        
        logger.info(f"Removed {len(removed_ids)} documents: {removed_ids}")
        
        return updated_docs, removed_ids
    
    def recalculate_totals_from_items(
        self,
        box1_items: list[Box1Income],
        box3_items: list[Box3Asset],
        removed_doc_ids: list[str]
    ) -> dict:
        """Recalculate Box 1/3 totals after document removal.
        
        Args:
            box1_items: List of Box 1 income items
            box3_items: List of Box 3 asset items
            removed_doc_ids: List of removed document IDs
            
        Returns:
            Dict with updated totals and filtered items
        """
        removed_doc_ids_set = set(removed_doc_ids)
        
        # Filter out items from removed documents
        updated_box1_items = [
            item for item in box1_items 
            if item.source_doc_id not in removed_doc_ids_set
        ]
        
        updated_box3_items = [
            item for item in box3_items
            if item.source_doc_id not in removed_doc_ids_set
        ]
        
        # Deduplicate Box 3 assets (same account_number, same source_doc_id, same values)
        # This handles cases where duplicates might exist due to processing issues
        deduplicated_box3_items = self._deduplicate_box3_assets(updated_box3_items)
        
        # Recalculate totals
        box1_total = sum(item.gross_amount_eur for item in updated_box1_items)
        box3_total = sum(item.value_eur_jan1 for item in deduplicated_box3_items)
        
        logger.info(
            f"Recalculated totals - Box 1: €{box1_total:,.2f}, Box 3: €{box3_total:,.2f} "
            f"(removed {len(box3_items) - len(deduplicated_box3_items)} duplicate assets)"
        )
        
        return {
            "box1_income_items": updated_box1_items,
            "box3_asset_items": deduplicated_box3_items,
            "box1_total_income": box1_total,
            "box3_total_assets_jan1": box3_total,
        }
    
    def _deduplicate_box3_assets(self, assets: list[Box3Asset]) -> list[Box3Asset]:
        """Remove duplicate Box 3 assets.
        
        Two assets are considered duplicates if they have:
        - Same source_doc_id
        - Same account_number (or both None)
        - Same asset_type
        - Same value_eur_jan1 (within 0.01 tolerance)
        - Same value_eur_dec31 (within 0.01 tolerance, or both None)
        
        Args:
            assets: List of Box 3 assets
            
        Returns:
            Deduplicated list of assets
        """
        seen = set()
        deduplicated = []
        
        for asset in assets:
            # Create a unique key for deduplication
            account_key = asset.account_number or ""
            jan1_key = round(asset.value_eur_jan1, 2)
            dec31_key = round(asset.value_eur_dec31 or 0.0, 2)
            
            dedup_key = (
                asset.source_doc_id,
                account_key,
                asset.asset_type,
                jan1_key,
                dec31_key
            )
            
            if dedup_key not in seen:
                seen.add(dedup_key)
                deduplicated.append(asset)
            else:
                logger.debug(
                    f"Removing duplicate asset: {asset.description} "
                    f"(doc_id: {asset.source_doc_id}, account: {account_key})"
                )
        
        return deduplicated
    
    def recalculate_from_extraction_results(
        self,
        extraction_results: list[ExtractionResult],
        removed_doc_ids: list[str]
    ) -> dict:
        """Recalculate totals from extraction results after document removal.
        
        This is used when we need to recalculate before aggregation has happened.
        
        Args:
            extraction_results: List of extraction results
            removed_doc_ids: List of removed document IDs
            
        Returns:
            Dict with updated extraction results
        """
        # Filter out extraction results from removed documents
        removed_doc_ids_set = set(removed_doc_ids)
        updated_results = [
            result for result in extraction_results
            if result.doc_id not in removed_doc_ids_set
        ]
        
        logger.info(
            f"Filtered extraction results: {len(updated_results)} remaining "
            f"(removed {len(extraction_results) - len(updated_results)})"
        )
        
        return {
            "extraction_results": updated_results,
        }
    
    def create_document_metadata(
        self,
        filename: str,
        doc_hash: str,
        page_count: int
    ) -> dict:
        """Create document metadata dict.
        
        Args:
            filename: Document filename
            doc_hash: SHA256 hash of document
            page_count: Number of pages
            
        Returns:
            Document metadata dict
        """
        return {
            "id": doc_hash[:12],  # Use first 12 chars of hash as ID
            "filename": filename,
            "hash": doc_hash,
            "page_count": page_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

