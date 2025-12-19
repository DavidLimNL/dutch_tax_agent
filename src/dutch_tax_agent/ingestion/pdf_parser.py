"""PDF parsing using pdfplumber (no OCR)."""

import logging
from pathlib import Path
from typing import Optional

import pdfplumber

from dutch_tax_agent.config import settings

logger = logging.getLogger(__name__)


class PDFParsingError(Exception):
    """Raised when PDF parsing fails."""

    pass


class PDFParser:
    """Extracts text from PDFs using pdfplumber (deterministic, no OCR)."""

    def __init__(self, min_chars: Optional[int] = None) -> None:
        """Initialize PDF parser.
        
        Args:
            min_chars: Minimum character count to consider a valid extraction.
                      Defaults to config setting.
        """
        self.min_chars = min_chars or settings.pdf_min_chars

    def parse(self, pdf_path: Path) -> dict:
        """Parse a PDF file and extract text.
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            dict with keys:
                - text: Extracted text content
                - page_count: Number of pages
                - char_count: Total character count
                - pages: List of per-page text (for audit trail)
                
        Raises:
            PDFParsingError: If parsing fails or text is too short
        """
        if not pdf_path.exists():
            raise PDFParsingError(f"PDF file not found: {pdf_path}")

        # Check file size
        file_size_mb = pdf_path.stat().st_size / (1024 * 1024)
        if file_size_mb > settings.max_document_size_mb:
            raise PDFParsingError(
                f"PDF too large: {file_size_mb:.2f}MB "
                f"(max: {settings.max_document_size_mb}MB)"
            )

        try:
            with pdfplumber.open(pdf_path) as pdf:
                pages_text = []
                full_text = []

                for page_num, page in enumerate(pdf.pages, start=1):
                    page_text = page.extract_text()

                    if page_text:
                        pages_text.append(
                            {"page_num": page_num, "text": page_text}
                        )
                        full_text.append(page_text)
                    else:
                        logger.warning(
                            f"Page {page_num} of {pdf_path.name} has no extractable text"
                        )

                # Combine all pages
                combined_text = "\n\n".join(full_text)
                char_count = len(combined_text)

                # Validate minimum character count
                if char_count < self.min_chars:
                    raise PDFParsingError(
                        f"Extracted text too short ({char_count} chars, "
                        f"minimum: {self.min_chars}). "
                        f"This might be a scanned document. "
                        f"We do not support OCR to avoid hallucinated numbers."
                    )

                logger.info(
                    f"Successfully parsed {pdf_path.name}: "
                    f"{len(pdf.pages)} pages, {char_count} chars"
                )

                return {
                    "text": combined_text,
                    "page_count": len(pdf.pages),
                    "char_count": char_count,
                    "pages": pages_text,
                }

        except pdfplumber.PDFSyntaxError as e:
            raise PDFParsingError(f"Invalid PDF format: {e}") from e
        except Exception as e:
            raise PDFParsingError(f"Failed to parse PDF: {e}") from e

    def parse_batch(self, pdf_paths: list[Path]) -> dict[str, dict]:
        """Parse multiple PDFs in batch.
        
        Args:
            pdf_paths: List of PDF file paths
            
        Returns:
            Dictionary mapping filename to parse result or error
        """
        results = {}

        for pdf_path in pdf_paths:
            try:
                result = self.parse(pdf_path)
                results[pdf_path.name] = {
                    "status": "success",
                    "data": result,
                }
            except PDFParsingError as e:
                logger.error(f"Failed to parse {pdf_path.name}: {e}")
                results[pdf_path.name] = {
                    "status": "error",
                    "error": str(e),
                }

        return results

