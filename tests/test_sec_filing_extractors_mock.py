"""
Mock/unit tests for SEC-5 deterministic filing section extraction.

These tests do not perform SEC network calls.

The fixtures construct SECFiling and SECFilingDocument instances locally so
that SEC-5 remains independently testable from SEC-3 and SEC-4 retrieval.

SEC-5.2 scanner tests additionally verify deterministic raw HTML source
position scanning without integrating HTML extraction into extract_sections().
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from sec_client import SECClient
from sec_filings import SECFiling, SECFilingDocument
from sec_filing_extractors import (
    SECFilingFormatError,
    SECFilingSection,
    SECFilingSectionError,
    extract_sections,
)


@pytest.fixture
def sec_client() -> SECClient:
    """Create a valid SECClient without performing network activity."""
    return SECClient(
        name="Test User",
        email="test@example.com",
        organization="Test Organization",
        requests_per_second=8.0,
        timeout=1.0,
    )


def _make_filing(
    form: str = "10-K",
    primary_document: str = "msft-20250630.htm",
) -> SECFiling:
    """Create deterministic representative SEC filing metadata."""
    return SECFiling(
        cik=789019,
        form=form,
        accession_number="0000789019-25-000123",
        filing_date="2025-08-01",
        report_date="2025-06-30",
        primary_document=primary_document,
        is_amendment=form.endswith("/A"),
        file_number="001-03756",
        filing_url=(
            "https://www.sec.gov/Archives/edgar/data/"
            "789019/000078901925000123/msft-20250630.htm"
        ),
    )


def _make_document(
    content: bytes,
    *,
    form: str = "10-K",
    content_type: str = "text/plain",
) -> SECFilingDocument:
    """Construct an immutable SEC filing document fixture."""
    filing = _make_filing(form=form)

    return SECFilingDocument(
        filing=filing,
        document_name=filing.primary_document or "filing.txt",
        document_kind="complete_submission",
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/"
            "789019/000078901925000123/"
            "0000789019-25-000123.txt"
        ),
        content_type=content_type,
        content_hash="fixture-hash",
        content=content,
    )


def test_section_contract_is_immutable() -> None:
    """SECFilingSection must be immutable because it represents evidence."""
    filing = _make_filing()
    document = _make_document(b"ITEM 1. Business\nExample")

    section = SECFilingSection(
        filing=filing,
        document=document,
        section_id="ITEM_1",
        section_title="Business",
        section_level=1,
        occurrence=1,
        start_offset=0,
        end_offset=len(document.content),
        content=document.content,
    )

    with pytest.raises(FrozenInstanceError):
        section.section_id = "ITEM_2"  # type: ignore[misc]


def test_section_content_exactly_matches_raw_document_slice() -> None:
    """Section evidence must be an exact raw-byte slice."""
    content = (
        b"ITEM 1. Business\n"
        b"Business content.\n"
        b"ITEM 1A. Risk Factors\n"
        b"Risk content.\n"
    )
    document = _make_document(content)

    sections = extract_sections(document)

    assert len(sections) == 2

    for section in sections:
        assert (
            section.content
            == document.content[section.start_offset : section.end_offset]
        )


def test_section_offsets_use_half_open_interval() -> None:
    """The section end offset must exclude the next section."""
    content = (
        b"ITEM 1. Business\n"
        b"Business content.\n"
        b"ITEM 1A. Risk Factors\n"
        b"Risk content.\n"
    )
    document = _make_document(content)

    sections = extract_sections(document)

    assert sections[0].start_offset == 0
    assert sections[0].end_offset == sections[1].start_offset
    assert sections[1].end_offset == len(content)


def test_sections_are_deterministically_ordered_by_raw_offset() -> None:
    """Extraction must return sections in source order."""
    content = (
        b"ITEM 7. Management's Discussion and Analysis\n"
        b"MD&A content.\n"
        b"ITEM 1. Business\n"
        b"Business content.\n"
        b"ITEM 8. Financial Statements and Supplementary Data\n"
        b"Financial statements.\n"
    )
    document = _make_document(content)

    sections = extract_sections(document)

    assert [section.section_id for section in sections] == [
        "ITEM_7",
        "ITEM_1",
        "ITEM_8",
    ]

    assert [
        section.start_offset for section in sections
    ] == sorted(section.start_offset for section in sections)


def test_missing_sections_are_tolerated() -> None:
    """A filing may omit a recognized section without causing extraction failure."""
    content = (
        b"ITEM 1. Business\n"
        b"Business content only.\n"
        b"ITEM 8. Financial Statements and Supplementary Data\n"
        b"Financial content.\n"
    )
    document = _make_document(content)

    sections = extract_sections(document)

    assert [section.section_id for section in sections] == [
        "ITEM_1",
        "ITEM_8",
    ]


def test_duplicate_section_headings_preserve_occurrence() -> None:
    """Duplicate recognized headings must remain separate evidence objects."""
    content = (
        b"ITEM 1. Business\n"
        b"First occurrence.\n"
        b"ITEM 1. Business\n"
        b"Second occurrence.\n"
    )
    document = _make_document(content)

    sections = extract_sections(document)

    assert len(sections) == 2
    assert [section.occurrence for section in sections] == [1, 2]
    assert [section.section_id for section in sections] == [
        "ITEM_1",
        "ITEM_1",
    ]

    assert b"First occurrence." in sections[0].content
    assert b"Second occurrence." in sections[1].content


def test_amended_supported_form_is_accepted() -> None:
    """10-K/A remains a supported base form."""
    content = (
        b"ITEM 1. Business\n"
        b"Amended business disclosure.\n"
    )
    document = _make_document(content, form="10-K/A")

    sections = extract_sections(document)

    assert len(sections) == 1
    assert sections[0].section_id == "ITEM_1"
    assert sections[0].filing.form == "10-K/A"


def test_unsupported_filing_form_is_rejected() -> None:
    """SEC-5 must not silently process unsupported filing forms."""
    filing = _make_filing(form="20-F")

    document = SECFilingDocument(
        filing=filing,
        document_name="foreign-filing.txt",
        document_kind="complete_submission",
        source_url="https://example.invalid/filing.txt",
        content_type="text/plain",
        content_hash="fixture-hash",
        content=b"ITEM 1. Business\nContent",
    )

    with pytest.raises(SECFilingFormatError, match="Unsupported SEC filing form"):
        extract_sections(document)


def test_invalid_document_object_is_rejected() -> None:
    """The public extractor must reject objects outside its contract."""
    with pytest.raises(SECFilingFormatError):
        extract_sections("not-a-filing-document")  # type: ignore[arg-type]


def test_empty_document_content_is_rejected() -> None:
    """Empty content is invalid rather than being treated as a missing section."""
    document = _make_document(b"")

    with pytest.raises(SECFilingFormatError, match="empty content"):
        extract_sections(document)


def test_html_extraction_is_explicitly_deferred() -> None:
    """HTML must not be parsed until byte-position mapping is implemented."""
    document = _make_document(
        b"<html><body><h1>ITEM 1. Business</h1></body></html>",
        content_type="text/html",
    )

    with pytest.raises(
        SECFilingFormatError,
        match="HTML/XML extraction is not implemented",
    ):
        extract_sections(document)


def test_repeated_extraction_is_deterministic() -> None:
    """Identical input must produce identical immutable extraction results."""
    content = (
        b"ITEM 1. Business\n"
        b"Business content.\n"
        b"ITEM 1A. Risk Factors\n"
        b"Risk content.\n"
        b"ITEM 7. Management's Discussion and Analysis\n"
        b"MD&A content.\n"
    )
    document = _make_document(content)

    first = extract_sections(document)
    second = extract_sections(document)

    assert first == second


def test_section_constructor_rejects_incorrect_raw_slice() -> None:
    """The evidence contract must reject content that does not match offsets."""
    document = _make_document(b"ITEM 1. Business\nContent")

    with pytest.raises(
        SECFilingSectionError,
        match="exactly equal",
    ):
        SECFilingSection(
            filing=document.filing,
            document=document,
            section_id="ITEM_1",
            section_title="Business",
            section_level=1,
            occurrence=1,
            start_offset=0,
            end_offset=5,
            content=b"incorrect",
        )


def test_section_constructor_rejects_inconsistent_filing_identity() -> None:
    """A section cannot associate one filing with another document."""
    document = _make_document(b"ITEM 1. Business\nContent")
    different_filing = _make_filing(
        primary_document="different-document.htm"
    )

    with pytest.raises(SECFilingSectionError, match="must match"):
        SECFilingSection(
            filing=different_filing,
            document=document,
            section_id="ITEM_1",
            section_title="Business",
            section_level=1,
            occurrence=1,
            start_offset=0,
            end_offset=len(document.content),
            content=document.content,
        )


# ---------------------------------------------------------------------------
# SEC-5.2 raw HTML source-position scanner tests
# ---------------------------------------------------------------------------


def test_raw_html_scanner_preserves_exact_byte_offsets() -> None:
    """Raw scanner offsets must remain valid against original bytes."""
    from sec_filing_extractors import _scan_raw_html

    content = (
        b"<html>\n"
        b"<body>\n"
        b"<h1>Item 1. Business</h1>\n"
        b"<p>Example &amp; test.</p>\n"
        b"</body>\n"
        b"</html>\n"
    )

    tokens = _scan_raw_html(content)

    assert tokens

    for token in tokens:
        assert 0 <= token.start_offset < token.end_offset <= len(content)
        assert content[token.start_offset : token.end_offset] != b""


def test_raw_html_scanner_identifies_nested_inline_markup() -> None:
    """Nested elements must retain independent exact source boundaries."""
    from sec_filing_extractors import _scan_raw_html

    content = (
        b"<h1>"
        b"Item 1. <ix:nonNumeric contextRef=\"ctx1\">Business</ix:nonNumeric>"
        b"</h1>"
    )

    tokens = _scan_raw_html(content)

    tag_tokens = [
        token
        for token in tokens
        if token.token_type in {"start_tag", "end_tag"}
    ]

    assert [
        (token.token_type, token.tag_name)
        for token in tag_tokens
    ] == [
        ("start_tag", b"h1"),
        ("start_tag", b"ix:nonnumeric"),
        ("end_tag", b"ix:nonnumeric"),
        ("end_tag", b"h1"),
    ]

    for token in tag_tokens:
        assert content[token.start_offset : token.end_offset].startswith(b"<")


def test_raw_html_scanner_handles_gt_inside_quoted_attribute() -> None:
    """A '>' inside a quoted attribute must not terminate the tag."""
    from sec_filing_extractors import _scan_raw_html

    content = (
        b'<div data-value="a > b">'
        b"content"
        b"</div>"
    )

    tokens = _scan_raw_html(content)

    assert [
        (token.token_type, token.tag_name)
        for token in tokens
        if token.token_type in {"start_tag", "end_tag"}
    ] == [
        ("start_tag", b"div"),
        ("end_tag", b"div"),
    ]

    start_tag = next(
        token
        for token in tokens
        if token.token_type == "start_tag"
    )

    assert content[start_tag.start_offset : start_tag.end_offset] == (
        b'<div data-value="a > b">'
    )


def test_raw_html_scanner_preserves_entities_as_raw_bytes() -> None:
    """HTML entities must not be decoded by the source scanner."""
    from sec_filing_extractors import _scan_raw_html

    content = b"<p>Example &amp; test &lt;value&gt;</p>"

    tokens = _scan_raw_html(content)

    text_token = next(
        token
        for token in tokens
        if token.token_type == "text"
    )

    assert content[text_token.start_offset : text_token.end_offset] == (
        b"Example &amp; test &lt;value&gt;"
    )


def test_raw_html_scanner_handles_comments_and_declarations() -> None:
    """Comments and declarations must have exact source boundaries."""
    from sec_filing_extractors import _scan_raw_html

    content = (
        b"<!DOCTYPE html>\n"
        b"<!-- SEC filing comment -->\n"
        b"<html></html>"
    )

    tokens = _scan_raw_html(content)

    structural = [
        token
        for token in tokens
        if token.token_type != "text"
    ]

    assert [token.token_type for token in structural] == [
        "declaration",
        "comment",
        "start_tag",
        "end_tag",
    ]

    for token in structural:
        assert content[token.start_offset : token.end_offset] == (
            content[token.start_offset : token.end_offset]
        )


def test_raw_html_scanner_is_deterministic() -> None:
    """Repeated scans of identical bytes must produce identical results."""
    from sec_filing_extractors import _scan_raw_html

    content = (
        b"<div><h1>Item 1A. Risk Factors</h1>"
        b"<p>Risk &amp; disclosure information.</p></div>"
    )

    assert _scan_raw_html(content) == _scan_raw_html(content)


def test_raw_html_scanner_treats_invalid_less_than_as_text() -> None:
    """A comparison operator must not be misclassified as an HTML tag."""
    from sec_filing_extractors import _scan_raw_html

    content = b"<p>x < y and z > x</p>"

    tokens = _scan_raw_html(content)

    assert any(
        token.token_type == "text"
        and content[token.start_offset : token.end_offset]
        == b"x < y and z > x"
        for token in tokens
    )