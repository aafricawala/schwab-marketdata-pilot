"""
test_sec_filing_extractors_live.py
Live integration tests for deterministic SEC filing section extraction.

These tests retrieve real SEC EDGAR filing documents through the existing
SEC-3/SEC-4 production clients and validate SEC-5.3 extraction behavior.

Requirements:
- Valid SEC User-Agent identity.
- Internet connectivity.
- SEC EDGAR availability.

These tests are intentionally separate from the offline mock tests.
"""

from __future__ import annotations

from sec_client import SECClient
from sec_filing_extractors import extract_sections
from sec_filings import SECFilingDocument, SECFilingsClient
from sec_submissions import SECFiling, SubmissionsClient


SEC_NAME = "Schwab Market Data Pilot"
SEC_EMAIL = "YOUR_EMAIL@example.com"
SEC_ORGANIZATION = "Schwab Market Data Pilot"

# MSFT is used only as a real validation sample.
# No MSFT-specific production behavior is exercised or assumed.
TEST_TICKER = "MSFT"

SUPPORTED_FORMS = {
    "10-K",
    "10-Q",
    "8-K",
    "10-K/A",
    "10-Q/A",
    "8-K/A",
}


def _get_live_clients() -> tuple[
    SECClient,
    SubmissionsClient,
    SECFilingsClient,
]:
    """Create the shared production SEC clients for live validation."""
    client = SECClient(
        name=SEC_NAME,
        email=SEC_EMAIL,
        organization=SEC_ORGANIZATION,
    )

    return (
        client,
        SubmissionsClient(client),
        SECFilingsClient(client),
    )


def _find_current_supported_filings(
    submissions_client: SubmissionsClient,
) -> list[SECFiling]:
    """Return currently available supported filings with primary documents."""
    filings = submissions_client.get_recent_filings_by_ticker(
        TEST_TICKER
    )

    assert filings, (
        f"No recent SEC filings were returned for {TEST_TICKER}."
    )

    assert all(
        isinstance(filing, SECFiling)
        for filing in filings
    )

    supported = [
        filing
        for filing in filings
        if (
            filing.form in SUPPORTED_FORMS
            and filing.primary_document
        )
    ]

    assert supported, (
        f"No supported filing with a primary document was found "
        f"for {TEST_TICKER}."
    )

    return supported


def _assert_extraction_contract(
    document: SECFilingDocument,
) -> tuple:
    """Validate the core SEC-5 section extraction contract."""
    sections = extract_sections(document)

    assert isinstance(sections, tuple)

    previous_start = -1

    for section in sections:
        assert section.filing is document.filing
        assert section.document is document

        assert section.start_offset >= 0
        assert section.start_offset < section.end_offset
        assert section.end_offset <= len(document.content)

        assert section.start_offset >= previous_start
        previous_start = section.start_offset

        assert section.content == document.content[
            section.start_offset : section.end_offset
        ]

        assert section.section_id
        assert section.section_title
        assert section.section_level >= 1
        assert section.occurrence >= 1

    return sections


def _is_inline_xbrl(document: SECFilingDocument) -> bool:
    """Detect inline-XBRL markup without interpreting filing data."""
    content_lower = document.content.lower()

    return (
        b"<ix:"
        in content_lower
        or b"</ix:"
        in content_lower
    )


def test_live_current_supported_filing_extraction() -> None:
    """Extract sections from a real current SEC primary filing."""
    (
        client,
        submissions_client,
        filings_client,
    ) = _get_live_clients()

    try:
        filings = _find_current_supported_filings(
            submissions_client
        )

        filing = filings[0]

        document = filings_client.get_primary_document(
            filing
        )

        assert isinstance(
            document,
            SECFilingDocument,
        )
        assert document.filing is filing
        assert document.document_kind == "primary"
        assert document.document_name == filing.primary_document
        assert document.content
        assert isinstance(document.content, bytes)
        assert document.content_hash

        _assert_extraction_contract(document)

    finally:
        client.close()


def test_live_supported_form_extraction_when_available() -> None:
    """Validate extraction for each distinct supported form currently available."""
    (
        client,
        submissions_client,
        filings_client,
    ) = _get_live_clients()

    try:
        filings = _find_current_supported_filings(
            submissions_client
        )

        forms_seen: set[str] = set()

        for filing in filings:
            if filing.form in forms_seen:
                continue

            forms_seen.add(filing.form)

            document = filings_client.get_primary_document(
                filing
            )

            assert isinstance(
                document,
                SECFilingDocument,
            )
            assert document.filing is filing
            assert document.content

            _assert_extraction_contract(document)

    finally:
        client.close()


def test_live_corpus_discovery_diagnostic() -> None:
    """Report the real SEC corpus available for SEC-5.3 validation.

    This test intentionally does not modify production behavior or require
    every corpus category to exist in the current recent-filings window.
    Its purpose is to expose the actual filings that should drive the next
    SEC-5.3 hardening increment.
    """
    (
        client,
        submissions_client,
        filings_client,
    ) = _get_live_clients()

    try:
        filings = _find_current_supported_filings(
            submissions_client
        )

        seen_forms: set[str] = set()
        seen_amendments: set[str] = set()
        seen_inline_xbrl: set[str] = set()

        print("\nSEC-5.3 LIVE CORPUS")

        for filing in filings:
            if filing.form in seen_forms:
                continue

            seen_forms.add(filing.form)

            document = filings_client.get_primary_document(
                filing
            )
            sections = _assert_extraction_contract(document)

            accession = filing.accession_number
            is_amended = filing.is_amendment
            inline_xbrl = _is_inline_xbrl(document)

            if is_amended:
                seen_amendments.add(filing.form)

            if inline_xbrl:
                seen_inline_xbrl.add(filing.form)

            section_ids = [
                section.section_id
                for section in sections
            ]

            print(
                f"FORM={filing.form} "
                f"ACCESSION={accession} "
                f"FILING_DATE={filing.filing_date} "
                f"REPORT_DATE={filing.report_date} "
                f"PRIMARY_DOCUMENT={filing.primary_document} "
                f"CONTENT_TYPE={document.content_type} "
                f"BYTES={len(document.content)} "
                f"SECTIONS={len(sections)} "
                f"AMENDED={is_amended} "
                f"INLINE_XBRL={inline_xbrl}"
            )
            print(
                f"SECTION_IDS={section_ids}"
            )

        print(
            f"FORMS_SEEN={sorted(seen_forms)}"
        )
        print(
            f"AMENDED_FORMS_SEEN={sorted(seen_amendments)}"
        )
        print(
            f"INLINE_XBRL_FORMS_SEEN={sorted(seen_inline_xbrl)}"
        )

        assert seen_forms

    finally:
        client.close()