"""Focused live diagnostic for SEC filing section extraction."""

import os

import pytest

from sec_client import SECClient
from sec_filing_extractors import extract_sections
from sec_filings import SECFilingsClient
from sec_submissions import SubmissionsClient


SEC_NAME = os.getenv("SEC_TEST_NAME", "Schwab Market Data Pilot")
SEC_EMAIL = os.getenv("SEC_TEST_EMAIL", "YOUR_EMAIL@example.com")
SEC_ORGANIZATION = os.getenv("SEC_TEST_ORGANIZATION", "Schwab Market Data Pilot")
TEST_TICKER = "MSFT"


def _create_live_clients():
    """Create the SEC clients used by the diagnostic."""
    if (
        not SEC_EMAIL
        or SEC_EMAIL == "YOUR_EMAIL@example.com"
        or "@" not in SEC_EMAIL
    ):
        pytest.skip("Set SEC_TEST_EMAIL to run live SEC diagnostics.")

    client = SECClient(
        name=SEC_NAME,
        email=SEC_EMAIL,
        organization=SEC_ORGANIZATION,
    )

    return client, SubmissionsClient(client), SECFilingsClient(client)


def test_msft_live_8k_extraction_diagnostic():
    """Print diagnostic information for the first recent MSFT 8-K."""
    client, submissions_client, filings_client = _create_live_clients()

    try:
        filings = submissions_client.get_recent_filings_by_ticker(TEST_TICKER)
        filing = next(
            (item for item in filings if item.form == "8-K"),
            None,
        )

        if filing is None:
            pytest.fail("No recent MSFT 8-K filing was found.")

        document = filings_client.get_primary_document(filing)
        sections = extract_sections(document)

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

        print("\n================ SECTIONS ================")
        print(f"SECTION COUNT:    {len(sections)}")

        for section in sections:
            print(
                f"{section.section_id}: "
                f"{section.start_offset}:{section.end_offset} "
                f"occurrence={section.occurrence}"
            )

    finally:
        client.close()
