"""
Temporary SEC-5.3 diagnostic for the real MSFT 8-K extractor failure.

This test reuses the exact production discovery/retrieval path already proven
by tests/test_sec_filing_extractors_live.py. It does not modify production
code or invoke the section extractor.

The purpose is to expose the raw HTML structure of the selected 8-K so the
production defect can be classified before changing sec_filing_extractors.py.
"""

from __future__ import annotations

import re

from test_sec_filing_extractors_live import (
    _find_first_filing,
    _get_recent_filings,
)


def _print_raw_item_matches(content: bytes) -> None:
    """Print bounded raw HTML surrounding recognized 8-K item text."""

    pattern = re.compile(
        rb"(?i)\bitem\s+[0-9]+\.[0-9]{2}\b"
    )

    matches = list(pattern.finditer(content))

    print(f"\nRAW ITEM MATCH COUNT: {len(matches)}")

    for index, match in enumerate(matches[:20], start=1):
        start = max(0, match.start() - 300)
        end = min(len(content), match.end() + 700)

        print(
            f"\n--- RAW ITEM MATCH {index} "
            f"OFFSET={match.start()} ---"
        )

        print(
            content[start:end].decode(
                "utf-8",
                errors="replace",
            )
        )


def _print_html_heading_candidates(content: bytes) -> None:
    """
    Print heading-like HTML elements containing 8-K item text.

    This is diagnostic only. It intentionally uses raw bytes so that the
    evidence remains independent of parser-normalized offsets.
    """

    pattern = re.compile(
        rb"(?is)"
        rb"<(h1|h2|h3|h4|h5|h6|p|div|span|td|th)"
        rb"\b[^>]*>"
        rb".{0,5000}?"
        rb"\bitem\s+[0-9]+\.[0-9]{2}\b"
        rb".{0,5000}?"
        rb"</\1\s*>"
    )

    matches = list(pattern.finditer(content))

    print(
        "\nHEADING-LIKE ELEMENT MATCH COUNT: "
        f"{len(matches)}"
    )

    for index, match in enumerate(matches[:20], start=1):
        print(
            f"\n--- HEADING-LIKE ELEMENT {index} "
            f"OFFSET={match.start()} ---"
        )

        print(
            match.group(0).decode(
                "utf-8",
                errors="replace",
            )[:6000]
        )


def test_debug_msft_live_8k_structure() -> None:
    """Expose the raw structure of the same MSFT 8-K selected by SEC-5.3."""

    (
        client,
        _submissions_client,
        filings_client,
        filings,
    ) = _get_recent_filings()

    try:
        filing = _find_first_filing(
            filings,
            "8-K",
        )

        document = filings_client.get_primary_document(
            filing,
        )

        print("\n================ FILING ================")
        print(f"CIK:              {filing.cik}")
        print(f"FORM:             {filing.form}")
        print(f"ACCESSION:        {filing.accession_number}")
        print(f"FILING DATE:      {filing.filing_date}")
        print(f"REPORT DATE:      {filing.report_date}")
        print(f"PRIMARY DOCUMENT: {filing.primary_document}")

        print("\n================ DOCUMENT ================")
        print(f"DOCUMENT NAME:    {document.document_name}")
        print(f"DOCUMENT KIND:    {document.document_kind}")
        print(f"CONTENT TYPE:     {document.content_type}")
        print(f"CONTENT LENGTH:   {len(document.content):,}")
        print(f"CONTENT HASH:     {document.content_hash}")
        print(f"SOURCE URL:       {document.source_url}")

        _print_raw_item_matches(document.content)
        _print_html_heading_candidates(document.content)

    finally:
        client.close()