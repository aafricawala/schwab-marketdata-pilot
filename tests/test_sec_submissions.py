"""
test_sec_submissions.py

Unit tests for sec_submissions.py.

Test strategy:
- No live SEC requests are performed.
- SECClient._get_json() is mocked.
- SECClient ticker -> CIK resolution is mocked where appropriate.
- Tests focus exclusively on SubmissionsClient behavior.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from sec_client import (
    SECConfigurationError,
    SECRequestError,
    SECTickerNotFoundError,
)

from sec_submissions import (
    SECFiling,
    SECSubmissionsDataError,
    SubmissionsClient,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_sec_client() -> Mock:
    """
    Create a mocked SECClient.

    The mock exposes only the SECClient methods required by
    SubmissionsClient, preventing all real network activity.
    """

    client = Mock()

    # Configure the ticker resolver with a deterministic test CIK.
    client.get_cik_by_ticker.return_value = 789019

    return client


@pytest.fixture
def submissions_client(mock_sec_client: Mock) -> SubmissionsClient:
    """
    Create a SubmissionsClient using the mocked SEC client.
    """

    return SubmissionsClient(mock_sec_client)


@pytest.fixture
def valid_submissions_response() -> dict:
    """
    Return a representative SEC Submissions API response.

    The response contains multiple filing types, an amendment,
    and one filing without a report date.
    """

    return {
        "name": "MICROSOFT CORP",
        "cik": "0000789019",
        "tickers": ["MSFT"],
        "exchanges": ["Nasdaq"],
        "filings": {
            "recent": {
                "form": [
                    "10-K",
                    "10-Q",
                    "10-K/A",
                    "8-K",
                ],
                "accessionNumber": [
                    "0000789019-25-000001",
                    "0000789019-25-000002",
                    "0000789019-25-000003",
                    "0000789019-25-000004",
                ],
                "filingDate": [
                    "2025-08-01",
                    "2025-05-01",
                    "2025-08-15",
                    "2025-09-01",
                ],
                "reportDate": [
                    "2025-06-30",
                    "2025-03-31",
                    "2025-06-30",
                    "",
                ],
                "primaryDocument": [
                    "msft-20250630.htm",
                    "msft-20250331.htm",
                    "msft-20250630a.htm",
                    "msft-20250901.htm",
                ],
                "fileNumber": [
                    "001-37845",
                    "001-37845",
                    "001-37845",
                    "001-37845",
                ],
            }
        },
    }


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------

def test_submissions_client_requires_sec_client() -> None:
    """
    Verify that SubmissionsClient rejects an invalid client object.
    """

    with pytest.raises(SECConfigurationError):
        SubmissionsClient(client=Mock())


def test_get_submissions_by_cik_rejects_non_integer(
    submissions_client: SubmissionsClient,
) -> None:
    """
    Verify that non-integer CIK values are rejected.
    """

    with pytest.raises(SECConfigurationError):
        submissions_client.get_submissions_by_cik("789019")


def test_get_submissions_by_cik_rejects_boolean(
    submissions_client: SubmissionsClient,
) -> None:
    """
    Verify that bool is rejected even though bool subclasses int.
    """

    with pytest.raises(SECConfigurationError):
        submissions_client.get_submissions_by_cik(True)


def test_get_submissions_by_cik_rejects_negative_cik(
    submissions_client: SubmissionsClient,
) -> None:
    """
    Verify that negative CIK values are rejected.
    """

    with pytest.raises(SECConfigurationError):
        submissions_client.get_submissions_by_cik(-1)


def test_get_submissions_by_ticker_rejects_empty_ticker(
    submissions_client: SubmissionsClient,
) -> None:
    """
    Verify that an empty ticker is rejected.
    """

    with pytest.raises(SECConfigurationError):
        submissions_client.get_submissions_by_ticker("")


def test_get_submissions_by_ticker_rejects_whitespace_ticker(
    submissions_client: SubmissionsClient,
) -> None:
    """
    Verify that whitespace-only tickers are rejected.
    """

    with pytest.raises(SECConfigurationError):
        submissions_client.get_submissions_by_ticker("   ")


# ---------------------------------------------------------------------------
# Valid response tests
# ---------------------------------------------------------------------------

def test_get_submissions_by_cik_returns_raw_response(
    submissions_client: SubmissionsClient,
    mock_sec_client: Mock,
    valid_submissions_response: dict,
) -> None:
    """
    Verify that a valid SEC response is returned without modification.
    """

    mock_sec_client._get_json.return_value = valid_submissions_response

    result = submissions_client.get_submissions_by_cik(789019)

    assert result == valid_submissions_response

    # Verify the SEC endpoint receives the correctly zero-padded CIK.
    mock_sec_client._get_json.assert_called_once_with(
        "https://data.sec.gov/submissions/CIK0000789019.json"
    )


def test_get_submissions_by_ticker_resolves_cik(
    submissions_client: SubmissionsClient,
    mock_sec_client: Mock,
    valid_submissions_response: dict,
) -> None:
    """
    Verify ticker -> CIK resolution before retrieving submissions.
    """

    mock_sec_client._get_json.return_value = valid_submissions_response

    result = submissions_client.get_submissions_by_ticker("msft")

    assert result == valid_submissions_response

    mock_sec_client.get_cik_by_ticker.assert_called_once_with("msft")


# ---------------------------------------------------------------------------
# Filing conversion tests
# ---------------------------------------------------------------------------

def test_get_recent_filings_by_cik_returns_filing_records(
    submissions_client: SubmissionsClient,
    mock_sec_client: Mock,
    valid_submissions_response: dict,
) -> None:
    """
    Verify conversion of SEC filing arrays into SECFiling records.
    """

    mock_sec_client._get_json.return_value = valid_submissions_response

    filings = submissions_client.get_recent_filings_by_cik(789019)

    assert len(filings) == 4

    assert all(
        isinstance(filing, SECFiling)
        for filing in filings
    )


def test_filing_metadata_is_preserved(
    submissions_client: SubmissionsClient,
    mock_sec_client: Mock,
    valid_submissions_response: dict,
) -> None:
    """
    Verify that filing metadata is mapped correctly.
    """

    mock_sec_client._get_json.return_value = valid_submissions_response

    filings = submissions_client.get_recent_filings_by_cik(789019)

    filing = filings[0]

    assert filing.cik == 789019
    assert filing.form == "10-K"
    assert filing.accession_number == "0000789019-25-000001"
    assert filing.filing_date == "2025-08-01"
    assert filing.report_date == "2025-06-30"
    assert filing.primary_document == "msft-20250630.htm"
    assert filing.file_number == "001-37845"
    assert filing.is_amendment is False


def test_amendment_is_detected(
    submissions_client: SubmissionsClient,
    mock_sec_client: Mock,
    valid_submissions_response: dict,
) -> None:
    """
    Verify that forms ending in /A are identified as amendments.
    """

    mock_sec_client._get_json.return_value = valid_submissions_response

    filings = submissions_client.get_recent_filings_by_cik(789019)

    amendment = filings[2]

    assert amendment.form == "10-K/A"
    assert amendment.is_amendment is True


def test_non_amendment_is_not_flagged(
    submissions_client: SubmissionsClient,
    mock_sec_client: Mock,
    valid_submissions_response: dict,
) -> None:
    """
    Verify that ordinary filings are not incorrectly marked as amendments.
    """

    mock_sec_client._get_json.return_value = valid_submissions_response

    filings = submissions_client.get_recent_filings_by_cik(789019)

    assert filings[0].is_amendment is False
    assert filings[1].is_amendment is False
    assert filings[3].is_amendment is False


# ---------------------------------------------------------------------------
# Filing URL tests
# ---------------------------------------------------------------------------

def test_filing_url_is_constructed_correctly(
    submissions_client: SubmissionsClient,
    mock_sec_client: Mock,
    valid_submissions_response: dict,
) -> None:
    """
    Verify deterministic EDGAR primary-document URL construction.
    """

    mock_sec_client._get_json.return_value = valid_submissions_response

    filings = submissions_client.get_recent_filings_by_cik(789019)

    assert (
        filings[0].filing_url
        == "https://www.sec.gov/Archives/edgar/data/"
        "789019/000078901925000001/msft-20250630.htm"
    )


def test_accession_hyphens_are_removed_from_url(
    submissions_client: SubmissionsClient,
) -> None:
    """
    Verify that accession numbers are normalized correctly for
    EDGAR archive paths.
    """

    url = submissions_client._build_filing_url(
        cik=789019,
        accession_number="0000789019-25-000001",
        primary_document="example.htm",
    )

    assert (
        url
        == "https://www.sec.gov/Archives/edgar/data/"
        "789019/000078901925000001/example.htm"
    )


# ---------------------------------------------------------------------------
# Optional metadata tests
# ---------------------------------------------------------------------------

def test_missing_file_number_is_allowed(
    submissions_client: SubmissionsClient,
    mock_sec_client: Mock,
    valid_submissions_response: dict,
) -> None:
    """
    Verify that fileNumber is optional in the SEC response.
    """

    response = valid_submissions_response.copy()

    response["filings"] = {
        "recent": response["filings"]["recent"].copy()
    }

    response["filings"]["recent"].pop("fileNumber")

    mock_sec_client._get_json.return_value = response

    filings = submissions_client.get_recent_filings_by_cik(789019)

    assert all(
        filing.file_number is None
        for filing in filings
    )


def test_empty_primary_document_produces_empty_url(
    submissions_client: SubmissionsClient,
    mock_sec_client: Mock,
    valid_submissions_response: dict,
) -> None:
    """
    Verify that a missing primary document does not produce an
    invalid URL.
    """

    response = valid_submissions_response.copy()

    response["filings"] = {
        "recent": response["filings"]["recent"].copy()
    }

    response["filings"]["recent"]["primaryDocument"][0] = ""

    mock_sec_client._get_json.return_value = response

    filings = submissions_client.get_recent_filings_by_cik(789019)

    assert filings[0].primary_document == ""
    assert filings[0].filing_url == ""


# ---------------------------------------------------------------------------
# Malformed response tests
# ---------------------------------------------------------------------------

def test_missing_filings_field_is_rejected(
    submissions_client: SubmissionsClient,
    mock_sec_client: Mock,
) -> None:
    """
    Verify rejection of a response missing the filings object.
    """

    mock_sec_client._get_json.return_value = {
        "name": "MICROSOFT CORP",
        "cik": "0000789019",
    }

    with pytest.raises(SECSubmissionsDataError):
        submissions_client.get_submissions_by_cik(789019)


def test_missing_recent_filings_is_rejected(
    submissions_client: SubmissionsClient,
    mock_sec_client: Mock,
) -> None:
    """
    Verify rejection when recent filing metadata is absent.
    """

    mock_sec_client._get_json.return_value = {
        "name": "MICROSOFT CORP",
        "cik": "0000789019",
        "filings": {},
    }

    with pytest.raises(SECSubmissionsDataError):
        submissions_client.get_submissions_by_cik(789019)


def test_missing_required_recent_array_is_rejected(
    submissions_client: SubmissionsClient,
    mock_sec_client: Mock,
) -> None:
    """
    Verify rejection when a required recent-filings array is absent.
    """

    mock_sec_client._get_json.return_value = {
        "name": "MICROSOFT CORP",
        "cik": "0000789019",
        "filings": {
            "recent": {
                "form": [],
                "accessionNumber": [],
                "filingDate": [],
                "reportDate": [],
            }
        },
    }

    with pytest.raises(SECSubmissionsDataError):
        submissions_client.get_submissions_by_cik(789019)


def test_inconsistent_filing_array_lengths_are_rejected(
    submissions_client: SubmissionsClient,
    mock_sec_client: Mock,
    valid_submissions_response: dict,
) -> None:
    """
    Verify that inconsistent SEC filing arrays are rejected rather
    than silently truncating or corrupting records.
    """

    response = valid_submissions_response.copy()

    response["filings"] = {
        "recent": response["filings"]["recent"].copy()
    }

    response["filings"]["recent"]["form"] = [
        "10-K"
    ]

    mock_sec_client._get_json.return_value = response

    with pytest.raises(SECSubmissionsDataError):
        submissions_client.get_recent_filings_by_cik(789019)


def test_invalid_form_type_is_rejected(
    submissions_client: SubmissionsClient,
    mock_sec_client: Mock,
    valid_submissions_response: dict,
) -> None:
    """
    Verify rejection of a filing record with an invalid form type.
    """

    response = valid_submissions_response.copy()

    response["filings"] = {
        "recent": response["filings"]["recent"].copy()
    }

    response["filings"]["recent"]["form"][0] = 10

    mock_sec_client._get_json.return_value = response

    with pytest.raises(SECSubmissionsDataError):
        submissions_client.get_recent_filings_by_cik(789019)


def test_invalid_accession_type_is_rejected(
    submissions_client: SubmissionsClient,
    mock_sec_client: Mock,
    valid_submissions_response: dict,
) -> None:
    """
    Verify rejection of a filing record with an invalid accession number.
    """

    response = valid_submissions_response.copy()

    response["filings"] = {
        "recent": response["filings"]["recent"].copy()
    }

    response["filings"]["recent"]["accessionNumber"][0] = 123

    mock_sec_client._get_json.return_value = response

    with pytest.raises(SECSubmissionsDataError):
        submissions_client.get_recent_filings_by_cik(789019)


def test_invalid_primary_document_type_is_rejected(
    submissions_client: SubmissionsClient,
    mock_sec_client: Mock,
    valid_submissions_response: dict,
) -> None:
    """
    Verify rejection of a filing record with an invalid primary document.
    """

    response = valid_submissions_response.copy()

    response["filings"] = {
        "recent": response["filings"]["recent"].copy()
    }

    response["filings"]["recent"]["primaryDocument"][0] = 123

    mock_sec_client._get_json.return_value = response

    with pytest.raises(SECSubmissionsDataError):
        submissions_client.get_recent_filings_by_cik(789019)


# ---------------------------------------------------------------------------
# Error propagation tests
# ---------------------------------------------------------------------------

def test_sec_request_error_propagates(
    submissions_client: SubmissionsClient,
    mock_sec_client: Mock,
) -> None:
    """
    Verify that SEC transport errors are not silently swallowed.
    """

    mock_sec_client._get_json.side_effect = SECRequestError(
        "SEC request failed."
    )

    with pytest.raises(SECRequestError):
        submissions_client.get_submissions_by_cik(789019)


def test_ticker_not_found_propagates(
    submissions_client: SubmissionsClient,
    mock_sec_client: Mock,
) -> None:
    """
    Verify that ticker-resolution failures propagate unchanged.
    """

    mock_sec_client.get_cik_by_ticker.side_effect = (
        SECTickerNotFoundError("Ticker not found.")
    )

    with pytest.raises(SECTickerNotFoundError):
        submissions_client.get_submissions_by_ticker("INVALID")