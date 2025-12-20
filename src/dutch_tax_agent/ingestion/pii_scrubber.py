"""PII scrubbing using Presidio with custom Dutch recognizers."""

import logging
import uuid
from typing import Optional

from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

from dutch_tax_agent.ingestion.recognizers import (
    BsnRecognizer,
    DutchAddressRecognizer,
    DutchDOBRecognizer,
    DutchIBANRecognizer,
    NameRecognizer,
)
from dutch_tax_agent.schemas.documents import ScrubbedDocument

logger = logging.getLogger(__name__)


class PIIScrubber:
    """Scrubs PII from text using Presidio with custom Dutch recognizers."""

    def __init__(self) -> None:
        """Initialize Presidio with custom recognizers."""
        # Initialize Presidio engines
        self.analyzer = AnalyzerEngine()
        self.anonymizer = AnonymizerEngine()

        # Register custom Dutch recognizers
        self.analyzer.registry.add_recognizer(BsnRecognizer())
        self.analyzer.registry.add_recognizer(DutchIBANRecognizer())
        self.analyzer.registry.add_recognizer(DutchDOBRecognizer())
        self.analyzer.registry.add_recognizer(DutchAddressRecognizer())
        self.analyzer.registry.add_recognizer(NameRecognizer())

        logger.info("Initialized PII scrubber with custom Dutch recognizers")

    def scrub(
        self,
        text: str,
        filename: str,
        page_count: int = 1,
        doc_id: Optional[str] = None,
    ) -> ScrubbedDocument:
        """Scrub PII from text.
        
        Args:
            text: Raw text to scrub
            filename: Original filename (for audit trail)
            page_count: Number of pages in source document
            doc_id: Optional document ID (generated if not provided)
            
        Returns:
            ScrubbedDocument with PII replaced by tokens
        """
        if not doc_id:
            doc_id = str(uuid.uuid4())

        # Define entities to detect and anonymization operators
        entities = [
            "NL_BSN",  # Custom Dutch BSN recognizer (includes "citizen service number")
            "NL_IBAN",  # Custom Dutch IBAN recognizer
            "NL_DATE_OF_BIRTH",  # Custom Dutch DOB recognizer
            "NL_ADDRESS",  # Custom Dutch address recognizer (postal codes, streets, cities)
            "PERSON_NAME",  # Custom name recognizer from pii_names.json
            "PERSON",  # Built-in person name detector (English) - kept as fallback
            "EMAIL_ADDRESS",  # Built-in email detector (English)
            "PHONE_NUMBER",  # Built-in phone detector (English)
            "LOCATION",  # Built-in location/address detector (English)
        ]

        operators = {
            "NL_BSN": OperatorConfig("replace", {"new_value": "<BSN_REDACTED>"}),
            "NL_IBAN": OperatorConfig("replace", {"new_value": "<IBAN_REDACTED>"}),
            "NL_DATE_OF_BIRTH": OperatorConfig(
                "replace", {"new_value": "<DOB_REDACTED>"}
            ),
            "NL_ADDRESS": OperatorConfig(
                "replace", {"new_value": "<ADDRESS_REDACTED>"}
            ),
            "PERSON_NAME": OperatorConfig("replace", {"new_value": "<NAME_REDACTED>"}),
            "PERSON": OperatorConfig("replace", {"new_value": "<NAME_REDACTED>"}),
            "EMAIL_ADDRESS": OperatorConfig(
                "replace", {"new_value": "<EMAIL_REDACTED>"}
            ),
            "PHONE_NUMBER": OperatorConfig(
                "replace", {"new_value": "<PHONE_REDACTED>"}
            ),
            "LOCATION": OperatorConfig("replace", {"new_value": "<ADDRESS_REDACTED>"}),
        }

        # Pass 1: Scrub normal text for PII entities
        # Using "en" as base language (English recognizers are available)
        # Custom Dutch recognizers (BSN, IBAN, DOB) work with "en" language setting
        normal_results = self.analyzer.analyze(
            text=text,
            language="en",
            entities=entities,
        )

        # Track all detected entity types for logging
        all_entity_types = set([result.entity_type for result in normal_results])

        # Anonymize the normal text
        anonymized_normal = self.anonymizer.anonymize(
            text=text,
            analyzer_results=normal_results,
            operators=operators,
        )

        # Pass 2: Scrub reversed text to catch inverted/reversed PII
        # We reverse the already-scrubbed text, scrub it again, then reverse back
        reversed_scrubbed_text = anonymized_normal.text[::-1]
        reversed_results = self.analyzer.analyze(
            text=reversed_scrubbed_text,
            language="en",
            entities=entities,
        )

        # Track entity types from reversed pass
        reversed_entity_types = set([result.entity_type for result in reversed_results])
        all_entity_types.update(reversed_entity_types)

        # Log if reversed text detection found anything
        if reversed_results:
            logger.info(
                f"Reversed text detection found {len(reversed_results)} "
                f"PII instance(s) in {filename}"
            )

        # Anonymize the reversed scrubbed text
        anonymized_reversed = self.anonymizer.anonymize(
            text=reversed_scrubbed_text,
            analyzer_results=reversed_results,
            operators=operators,
        )

        # Reverse back to original orientation
        final_scrubbed_text = anonymized_reversed.text[::-1]

        # Log detected entities
        if all_entity_types:
            logger.info(
                f"Detected PII in {filename}: {', '.join(sorted(all_entity_types))} "
                f"({len(normal_results)} from normal text, "
                f"{len(reversed_results)} from reversed text)"
            )

        # Create scrubbed document
        scrubbed_doc = ScrubbedDocument(
            doc_id=doc_id,
            filename=filename,
            scrubbed_text=final_scrubbed_text,
            page_count=page_count,
            char_count=len(final_scrubbed_text),
            scrubbed_entities=list(all_entity_types),
        )

        logger.info(
            f"Successfully scrubbed {filename}: "
            f"{len(all_entity_types)} entity types, "
            f"{len(final_scrubbed_text)} chars"
        )

        return scrubbed_doc

    def scrub_batch(
        self, documents: list[dict]
    ) -> list[ScrubbedDocument]:
        """Scrub multiple documents in batch.
        
        ZERO-TRUST POLICY: Documents that fail scrubbing are NOT passed through.
        This ensures no unredacted PII ever reaches the LLM.
        
        Args:
            documents: List of dicts with keys:
                - text: Raw text
                - filename: Original filename
                - page_count: Number of pages
                
        Returns:
            List of ScrubbedDocument objects (only successfully scrubbed documents)
            
        Raises:
            RuntimeError: If all documents fail to scrub (security violation)
        """
        scrubbed_docs = []
        failed_docs = []

        for doc in documents:
            try:
                scrubbed = self.scrub(
                    text=doc["text"],
                    filename=doc["filename"],
                    page_count=doc.get("page_count", 1),
                )
                scrubbed_docs.append(scrubbed)
            except Exception as e:
                logger.error(
                    f"SECURITY: Failed to scrub {doc['filename']}: {e}. "
                    f"Document will NOT be processed (PII protection)."
                )
                failed_docs.append(doc["filename"])
                # DO NOT pass through - this would violate Zero-Trust policy

        if not scrubbed_docs and documents:
            # All documents failed - this is a critical security issue
            raise RuntimeError(
                f"SECURITY VIOLATION: All {len(documents)} documents failed PII scrubbing. "
                f"Failed files: {', '.join(failed_docs)}. "
                f"No documents will be processed to prevent PII exposure."
            )
        
        if failed_docs:
            logger.warning(
                f"{len(failed_docs)} document(s) failed scrubbing and were excluded: "
                f"{', '.join(failed_docs)}"
            )

        return scrubbed_docs

