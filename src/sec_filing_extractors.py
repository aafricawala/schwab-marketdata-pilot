"""
Deterministic SEC filing section extraction.

SEC-5 first increment:
    - Defines the immutable SECFilingSection evidence contract.
    - Defines filing-type-aware deterministic section taxonomies.
    - Supports plain-text filing extraction.
    - Preserves exact raw-byte section boundaries.
    - Does not perform financial interpretation or LLM-based extraction.

SEC-5.2 incremental work:
    - Adds a deterministic raw HTML source-position scanner.
    - Preserves exact byte offsets in the original filing document.
    - Recognizes nested HTML / inline-XBRL elements.
    - Handles quoted attributes containing '>'.
    - Preserves HTML entities without decoding them.
    - Recognizes comments, declarations, and processing instructions.
    - Does not yet integrate HTML scanning into extract_sections().

HTML / inline-XBRL structural extraction remains deferred until the raw
source-position scanner can be integrated with lxml structural interpretation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Optional

from sec_filings import SECFiling, SECFilingDocument


class SECFilingExtractionError(Exception):
    """Base exception for deterministic SEC filing extraction failures."""


class SECFilingFormatError(SECFilingExtractionError):
    """Raised when a filing document has an unsupported or malformed format."""


class SECFilingSectionError(SECFilingExtractionError):
    """Raised when a filing section contract or boundary is invalid."""


# SEC filing forms supported by SEC-5.
_SUPPORTED_FORMS: Final[frozenset[str]] = frozenset({"10-K", "10-Q", "8-K"})


# ---------------------------------------------------------------------------
# Raw HTML source-position scanning
# ---------------------------------------------------------------------------
#
# The HTML parser is intentionally NOT used to establish authoritative byte
# offsets. HTML parsers may decode entities, repair malformed markup, merge
# nodes, or otherwise normalize the source.
#
# This scanner operates directly on the original raw bytes and therefore
# preserves the exact source-position contract required by SECFilingSection:
#
#     section.content == document.content[start_offset:end_offset]
#
# The scanner is deliberately structural rather than semantic. It identifies
# raw HTML tag boundaries and provides enough information for the higher-level
# extractor to correlate lxml's structural interpretation with the original
# source document.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _RawHTMLToken:
    """Immutable representation of one raw HTML lexical token.

    Offsets are byte offsets into the original SECFilingDocument.content.
    The end offset is exclusive.

    token_type values currently include:
        - "start_tag"
        - "end_tag"
        - "comment"
        - "declaration"
        - "processing_instruction"
        - "text"

    The scanner intentionally does not decode the token content.
    """

    token_type: str
    start_offset: int
    end_offset: int
    tag_name: Optional[bytes] = None


# HTML tag names are ASCII by definition. Restricting the scanner to this
# conservative grammar prevents arbitrary text containing "<" from being
# incorrectly interpreted as a tag.
_HTML_TAG_NAME_CHARS = frozenset(
    b"abcdefghijklmnopqrstuvwxyz"
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    b"0123456789"
    b":_-"
)


def _is_html_tag_name_start(value: int) -> bool:
    """Return whether a byte can begin an HTML tag name."""

    return (
        65 <= value <= 90
        or 97 <= value <= 122
    )


def _is_html_tag_name_byte(value: int) -> bool:
    """Return whether a byte can occur inside an HTML tag name."""

    return value in _HTML_TAG_NAME_CHARS


def _find_tag_end(content: bytes, start_offset: int) -> int:
    """Find the end of an HTML tag while respecting quoted attributes.

    Args:
        content: Original raw HTML bytes.
        start_offset: Offset of the '<' beginning the tag.

    Returns:
        Exclusive end offset immediately after the closing '>'.

    Raises:
        SECFilingFormatError:
            If the tag is unterminated.

    Security:
        Attribute values are scanned while respecting single and double
        quotes so a '>' contained inside an attribute cannot prematurely
        terminate the tag.
    """

    quote: Optional[int] = None
    index = start_offset + 1
    length = len(content)

    while index < length:
        current = content[index]

        if quote is not None:
            if current == quote:
                quote = None
        elif current == 34 or current == 39:  # '"' or "'"
            quote = current
        elif current == 62:  # '>'
            return index + 1

        index += 1

    raise SECFilingFormatError(
        "Unterminated HTML tag encountered while scanning raw filing content."
    )


def _find_comment_end(content: bytes, start_offset: int) -> int:
    """Find the exclusive end offset of an HTML comment."""

    end_marker = content.find(b"-->", start_offset + 4)

    if end_marker < 0:
        raise SECFilingFormatError(
            "Unterminated HTML comment encountered while scanning "
            "raw filing content."
        )

    return end_marker + 3


def _find_processing_instruction_end(
    content: bytes,
    start_offset: int,
) -> int:
    """Find the exclusive end offset of a processing instruction."""

    end_marker = content.find(b"?>", start_offset + 2)

    if end_marker < 0:
        raise SECFilingFormatError(
            "Unterminated processing instruction encountered while "
            "scanning raw filing content."
        )

    return end_marker + 2


def _extract_raw_tag_name(
    content: bytes,
    start_offset: int,
    end_offset: int,
) -> Optional[bytes]:
    """Extract a normalized raw HTML tag name from a tag token.

    The returned value is ASCII bytes converted to lowercase. The source
    offsets themselves remain untouched.

    Returns:
        Lowercase tag name, or None when the token is not a normal HTML tag.
    """

    index = start_offset + 1

    # Skip an optional '/' for an end tag.
    if index < end_offset and content[index] == 47:
        index += 1

    # Skip whitespace defensively. Normal HTML syntax does not require this
    # after '<', but malformed SEC filings occasionally contain it.
    while index < end_offset and content[index] in b" \t\r\n\f":
        index += 1

    if index >= end_offset:
        return None

    if not _is_html_tag_name_start(content[index]):
        return None

    name_start = index
    index += 1

    while index < end_offset and _is_html_tag_name_byte(content[index]):
        index += 1

    return content[name_start:index].lower()


def _scan_raw_html(content: bytes) -> tuple[_RawHTMLToken, ...]:
    """Scan original HTML bytes into deterministic structural tokens.

    This function does not parse HTML semantics and does not modify content.
    Every returned offset refers directly to the original byte sequence.

    Text between structural tokens is represented explicitly so callers can
    establish exact source ranges without reconstructing content from parser
    output.

    Args:
        content: Raw filing document bytes.

    Returns:
        Immutable ordered tuple of raw HTML tokens.

    Raises:
        SECFilingFormatError:
            If a structural token cannot be terminated safely.
    """

    if not isinstance(content, bytes):
        raise SECFilingFormatError(
            "Raw HTML scanner requires document content as bytes."
        )

    if not content:
        return ()

    tokens: list[_RawHTMLToken] = []
    length = len(content)
    text_start = 0
    index = 0

    while index < length:
        # Fast path: most bytes are ordinary text.
        if content[index] != 60:  # '<'
            index += 1
            continue

        # Preserve ordinary text preceding this structural token.
        if text_start < index:
            tokens.append(
                _RawHTMLToken(
                    token_type="text",
                    start_offset=text_start,
                    end_offset=index,
                )
            )

        # HTML comment.
        if content.startswith(b"<!--", index):
            end_offset = _find_comment_end(content, index)
            tokens.append(
                _RawHTMLToken(
                    token_type="comment",
                    start_offset=index,
                    end_offset=end_offset,
                )
            )
            index = end_offset
            text_start = index
            continue

        # XML/HTML declaration such as <!DOCTYPE html>.
        if content.startswith(b"<!", index):
            end_offset = _find_tag_end(content, index)
            tokens.append(
                _RawHTMLToken(
                    token_type="declaration",
                    start_offset=index,
                    end_offset=end_offset,
                )
            )
            index = end_offset
            text_start = index
            continue

        # Processing instruction, including XML declarations.
        if content.startswith(b"<?", index):
            end_offset = _find_processing_instruction_end(content, index)
            tokens.append(
                _RawHTMLToken(
                    token_type="processing_instruction",
                    start_offset=index,
                    end_offset=end_offset,
                )
            )
            index = end_offset
            text_start = index
            continue

        # A '<' that is not followed by a plausible tag name or end-tag
        # marker is treated as ordinary text. This is important for malformed
        # filing content containing comparison operators such as "x < y".
        candidate_index = index + 1

        if candidate_index < length and content[candidate_index] == 47:
            candidate_index += 1

        if (
            candidate_index >= length
            or not _is_html_tag_name_start(content[candidate_index])
        ):
            index += 1
            continue

        end_offset = _find_tag_end(content, index)

        tag_name = _extract_raw_tag_name(
            content,
            index,
            end_offset,
        )

        # Defensive guard: a syntactically valid candidate should always
        # produce a tag name.
        if tag_name is None:
            index += 1
            continue

        is_end_tag = content[index + 1:index + 2] == b"/"

        tokens.append(
            _RawHTMLToken(
                token_type="end_tag" if is_end_tag else "start_tag",
                start_offset=index,
                end_offset=end_offset,
                tag_name=tag_name,
            )
        )

        index = end_offset
        text_start = index

    # Preserve trailing raw text.
    if text_start < length:
        tokens.append(
            _RawHTMLToken(
                token_type="text",
                start_offset=text_start,
                end_offset=length,
            )
        )

    return tuple(tokens)


# ---------------------------------------------------------------------------
# Filing section taxonomy
# ---------------------------------------------------------------------------
#
# The taxonomy contains section identifiers that SEC-5 recognizes
# deterministically. The extractor does not require every section to exist.
# Missing sections are normal because filings vary by issuer, amendment,
# reporting period, and SEC filing structure.
#
# section_id is the stable machine-readable identity.
# title is the expected canonical title.
# level is the structural level used by the section contract.
#

_SECTION_TAXONOMY: Final[dict[str, tuple[tuple[str, str, int], ...]]] = {
    "10-K": (
        ("ITEM_1", "Business", 1),
        ("ITEM_1A", "Risk Factors", 1),
        ("ITEM_1B", "Unresolved Staff Comments", 1),
        ("ITEM_1C", "Cybersecurity", 1),
        ("ITEM_2", "Properties", 1),
        ("ITEM_3", "Legal Proceedings", 1),
        ("ITEM_4", "Mine Safety Disclosures", 1),
        ("ITEM_5", "Market for Registrant's Common Equity", 1),
        ("ITEM_6", "Reserved", 1),
        ("ITEM_7", "Management's Discussion and Analysis", 1),
        (
            "ITEM_7A",
            "Quantitative and Qualitative Disclosures About Market Risk",
            1,
        ),
        ("ITEM_8", "Financial Statements and Supplementary Data", 1),
        (
            "ITEM_9",
            "Changes in and Disagreements With Accountants",
            1,
        ),
        ("ITEM_9A", "Controls and Procedures", 1),
        ("ITEM_9B", "Other Information", 1),
        ("ITEM_9C", "Disclosure Regarding Foreign Jurisdictions", 1),
    ),
    "10-Q": (
        ("PART_I_ITEM_1", "Financial Statements", 2),
        ("PART_I_ITEM_2", "Management's Discussion and Analysis", 2),
        (
            "PART_I_ITEM_3",
            "Quantitative and Qualitative Disclosures About Market Risk",
            2,
        ),
        ("PART_I_ITEM_4", "Controls and Procedures", 2),
        ("PART_II_ITEM_1", "Legal Proceedings", 2),
        ("PART_II_ITEM_1A", "Risk Factors", 2),
        ("PART_II_ITEM_2", "Unregistered Sales of Equity Securities", 2),
        ("PART_II_ITEM_3", "Defaults Upon Senior Securities", 2),
        ("PART_II_ITEM_4", "Mine Safety Disclosures", 2),
        ("PART_II_ITEM_5", "Other Information", 2),
        ("PART_II_ITEM_6", "Exhibits", 2),
    ),
    "8-K": (
        ("ITEM_1_01", "Entry into a Material Definitive Agreement", 1),
        (
            "ITEM_1_02",
            "Termination of a Material Definitive Agreement",
            1,
        ),
        ("ITEM_1_03", "Bankruptcy or Receivership", 1),
        ("ITEM_1_04", "Mine Safety Reporting", 1),
        ("ITEM_1_05", "Material Cybersecurity Incidents", 1),
        (
            "ITEM_2_01",
            "Completion of Acquisition or Disposition of Assets",
            1,
        ),
        (
            "ITEM_2_02",
            "Results of Operations and Financial Condition",
            1,
        ),
        (
            "ITEM_2_03",
            "Creation of a Direct Financial Obligation",
            1,
        ),
        (
            "ITEM_2_04",
            "Triggering Events That Accelerate or Increase "
            "a Direct Financial Obligation",
            1,
        ),
        (
            "ITEM_2_05",
            "Costs Associated With Exit or Disposal Activities",
            1,
        ),
        ("ITEM_2_06", "Material Impairments", 1),
        (
            "ITEM_3_01",
            "Notice of Delisting or Failure to Satisfy "
            "a Continued Listing Rule",
            1,
        ),
        ("ITEM_3_02", "Unregistered Sales of Equity Securities", 1),
        (
            "ITEM_3_03",
            "Material Modification to Rights of Security Holders",
            1,
        ),
        (
            "ITEM_4_01",
            "Changes in Registrant's Certifying Accountant",
            1,
        ),
        (
            "ITEM_4_02",
            "Non-Reliance on Previously Issued Financial Statements",
            1,
        ),
        ("ITEM_5_01", "Changes in Control of Registrant", 1),
        (
            "ITEM_5_02",
            "Departure of Directors or Certain Officers",
            1,
        ),
        (
            "ITEM_5_03",
            "Amendments to Articles of Incorporation or Bylaws",
            1,
        ),
        ("ITEM_5_04", "Temporary Suspension of Trading", 1),
        (
            "ITEM_5_05",
            "Amendment to Registrant's Code of Ethics",
            1,
        ),
        ("ITEM_5_06", "Change in Shell Company Status", 1),
        ("ITEM_5_07", "Submission of Matters to a Vote", 1),
        ("ITEM_5_08", "Shareholder Director Nominations", 1),
        (
            "ITEM_6_01",
            "ABS Informational and Computational Material",
            1,
        ),
        ("ITEM_6_02", "Change of Servicer or Trustee", 1),
        ("ITEM_6_03", "Change in Credit Enhancement", 1),
        (
            "ITEM_6_04",
            "Failure to Make a Required Distribution",
            1,
        ),
        (
            "ITEM_6_05",
            "Securities Act Updating Disclosure",
            1,
        ),
        ("ITEM_7_01", "Regulation FD Disclosure", 1),
        ("ITEM_8_01", "Other Events", 1),
        ("ITEM_9_01", "Financial Statements and Exhibits", 1),
    ),
}


# ---------------------------------------------------------------------------
# Plain-text heading recognition
# ---------------------------------------------------------------------------
#
# The pattern is deliberately line-oriented. It is not intended to parse
# arbitrary prose occurrences such as "Item 1 discusses..." inside a paragraph.
#
# Examples recognized:
#     ITEM 1. BUSINESS
#     Item 1A. Risk Factors
#     ITEM 7 - Management's Discussion and Analysis
#     PART I
#     ITEM 1. Financial Statements
#
# The pattern captures only the structural heading line. Canonical section
# identity is resolved separately from the filing-specific taxonomy.
#

_ITEM_HEADING_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[ \t]*ITEM[ \t]+"
    r"(?P<number>\d+)"
    r"(?P<letter>[A-Z])?"
    r"(?:[ \t]*[.:)\-–—]?[ \t]*)"
    r"(?P<title>.*?)"
    r"[ \t]*$",
    re.IGNORECASE,
)

_PART_HEADING_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[ \t]*PART[ \t]+(?P<part>[IVX]+)"
    r"(?:[ \t]*[.:)\-–—]?[ \t]*)"
    r"(?P<title>.*?)"
    r"[ \t]*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SECFilingSection:
    """
    Immutable evidence object representing one deterministic filing section.

    Offsets use half-open semantics:

        [start_offset, end_offset)

    and refer directly to the original raw bytes contained in the
    SECFilingDocument.

    Therefore the fundamental evidence invariant is:

        content == document.content[start_offset:end_offset]
    """

    filing: SECFiling
    document: SECFilingDocument
    section_id: str
    section_title: str
    section_level: int
    occurrence: int
    start_offset: int
    end_offset: int
    content: bytes

    def __post_init__(self) -> None:
        """Validate the immutable section evidence contract."""
        if not isinstance(self.filing, SECFiling):
            raise SECFilingSectionError("filing must be a SECFiling instance.")

        if not isinstance(self.document, SECFilingDocument):
            raise SECFilingSectionError(
                "document must be a SECFilingDocument instance."
            )

        if self.document.filing != self.filing:
            raise SECFilingSectionError(
                "document.filing must match the section filing."
            )

        if not isinstance(self.section_id, str) or not self.section_id.strip():
            raise SECFilingSectionError("section_id must be a non-empty string.")

        if not isinstance(self.section_title, str) or not self.section_title.strip():
            raise SECFilingSectionError(
                "section_title must be a non-empty string."
            )

        if not isinstance(self.section_level, int) or self.section_level < 1:
            raise SECFilingSectionError(
                "section_level must be a positive integer."
            )

        if not isinstance(self.occurrence, int) or self.occurrence < 1:
            raise SECFilingSectionError(
                "occurrence must be a positive integer."
            )

        if not isinstance(self.start_offset, int) or self.start_offset < 0:
            raise SECFilingSectionError(
                "start_offset must be a non-negative integer."
            )

        if not isinstance(self.end_offset, int) or self.end_offset < 0:
            raise SECFilingSectionError(
                "end_offset must be a non-negative integer."
            )

        if self.end_offset < self.start_offset:
            raise SECFilingSectionError(
                "end_offset must be greater than or equal to start_offset."
            )

        if not isinstance(self.content, bytes):
            raise SECFilingSectionError("content must be bytes.")

        document_length = len(self.document.content)

        if self.end_offset > document_length:
            raise SECFilingSectionError(
                "Section end_offset exceeds the document content length."
            )

        expected_content = self.document.content[
            self.start_offset : self.end_offset
        ]

        if self.content != expected_content:
            raise SECFilingSectionError(
                "content must exactly equal the corresponding raw document slice."
            )


@dataclass(frozen=True)
class _HeadingCandidate:
    """Internal immutable representation of a recognized text heading."""

    item_number: str
    title: str
    start_offset: int
    end_offset: int


@dataclass(frozen=True)
class _TaxonomyEntry:
    """Internal immutable filing taxonomy entry."""

    section_id: str
    title: str
    level: int


def _get_base_form(form: str) -> str:
    """
    Return the base SEC form for an original filing or amendment.

    Examples:
        10-K  -> 10-K
        10-K/A -> 10-K
        8-K/A  -> 8-K
    """
    if not isinstance(form, str) or not form.strip():
        raise SECFilingFormatError("Filing form must be a non-empty string.")

    normalized = form.strip().upper()

    if normalized.endswith("/A"):
        normalized = normalized[:-2]

    return normalized


def _validate_document(document: SECFilingDocument) -> str:
    """
    Validate the input document and return its supported base filing form.
    """
    if not isinstance(document, SECFilingDocument):
        raise SECFilingFormatError(
            "document must be a SECFilingDocument instance."
        )

    base_form = _get_base_form(document.filing.form)

    if base_form not in _SUPPORTED_FORMS:
        raise SECFilingFormatError(
            f"Unsupported SEC filing form: {document.filing.form!r}."
        )

    if not isinstance(document.content, bytes):
        raise SECFilingFormatError("SECFilingDocument.content must be bytes.")

    if not document.content:
        raise SECFilingFormatError("Cannot extract sections from empty content.")

    return base_form


def _decode_plain_text(content: bytes) -> str:
    """
    Decode raw filing bytes for structural parsing.

    The decoded string is parsing-only. Section offsets are subsequently
    calculated against the original bytes, so decoded text never becomes the
    authoritative evidence representation.

    UTF-8 is attempted first. Latin-1 is used as a deterministic fallback
    because it provides a one-byte-to-one-code-point mapping for arbitrary
    byte values and therefore preserves positional correspondence.
    """
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("latin-1")


def _line_start_offsets(content: bytes) -> tuple[int, ...]:
    """
    Return the raw-byte offset of every decoded text line.

    This implementation intentionally treats LF as the primary line
    delimiter and preserves CRLF bytes as part of the preceding line.
    """
    offsets = [0]

    for match in re.finditer(b"\n", content):
        offsets.append(match.end())

    return tuple(offsets)


def _normalize_title(title: str) -> str:
    """Normalize a heading title for deterministic taxonomy matching."""
    normalized = re.sub(r"\s+", " ", title.strip())
    normalized = normalized.strip(" .:-–—\t")
    return normalized.casefold()


def _extract_heading_candidates(
    content: bytes,
    base_form: str,
) -> tuple[_HeadingCandidate, ...]:
    """
    Identify structurally plausible Item headings in plain-text content.

    The returned offsets refer directly to the original raw bytes because
    ASCII SEC Item/Part heading syntax is byte-compatible with the decoding
    performed by _decode_plain_text().
    """
    text = _decode_plain_text(content)
    line_offsets = _line_start_offsets(content)

    lines = text.splitlines(keepends=True)
    candidates: list[_HeadingCandidate] = []

    offset_index = 0

    for line in lines:
        line_without_ending = line.rstrip("\r\n")

        item_match = _ITEM_HEADING_PATTERN.match(line_without_ending)

        if item_match:
            number = item_match.group("number")
            letter = item_match.group("letter") or ""
            item_number = f"{number}{letter}".upper()

            title = item_match.group("title").strip()

            start_offset = line_offsets[offset_index]
            end_offset = start_offset + len(line.encode("utf-8"))

            # For Latin-1 fallback, the heading itself is expected to be ASCII.
            # Recalculate from the original bytes if UTF-8 byte length differs.
            if len(line.encode("utf-8")) > len(content) - start_offset:
                end_offset = len(content)

            candidates.append(
                _HeadingCandidate(
                    item_number=item_number,
                    title=title,
                    start_offset=start_offset,
                    end_offset=end_offset,
                )
            )

        offset_index += 1

    return tuple(candidates)


def _build_taxonomy(base_form: str) -> dict[str, _TaxonomyEntry]:
    """
    Build a deterministic lookup table for one filing form.
    """
    entries: dict[str, _TaxonomyEntry] = {}

    for section_id, title, level in _SECTION_TAXONOMY[base_form]:
        entries[section_id] = _TaxonomyEntry(
            section_id=section_id,
            title=title,
            level=level,
        )

    return entries


def _taxonomy_key(
    base_form: str,
    item_number: str,
    title: str,
) -> str | None:
    """
    Resolve one recognized Item heading to the filing taxonomy.

    Title matching is used to distinguish repeated item numbers where
    necessary, such as 10-Q Part I Item 1 versus Part II Item 1.
    """
    normalized_title = _normalize_title(title)

    if base_form == "10-K":
        return f"ITEM_{item_number}"

    if base_form == "8-K":
        return f"ITEM_{item_number.replace('.', '_')}"

    # 10-Q requires Part context. Plain-text parsing in this first increment
    # does not infer Part from arbitrary prose; therefore Item 1 is mapped
    # according to its recognized title when it is unambiguous.
    if base_form == "10-Q":
        title_to_part_i = {
            _normalize_title("Financial Statements"): "PART_I_ITEM_1",
            _normalize_title(
                "Management's Discussion and Analysis"
            ): "PART_I_ITEM_2",
            _normalize_title(
                "Quantitative and Qualitative Disclosures About Market Risk"
            ): "PART_I_ITEM_3",
            _normalize_title("Controls and Procedures"): "PART_I_ITEM_4",
        }

        title_to_part_ii = {
            _normalize_title("Legal Proceedings"): "PART_II_ITEM_1",
            _normalize_title("Risk Factors"): "PART_II_ITEM_1A",
            _normalize_title(
                "Unregistered Sales of Equity Securities"
            ): "PART_II_ITEM_2",
            _normalize_title("Defaults Upon Senior Securities"): "PART_II_ITEM_3",
            _normalize_title("Mine Safety Disclosures"): "PART_II_ITEM_4",
            _normalize_title("Other Information"): "PART_II_ITEM_5",
            _normalize_title("Exhibits"): "PART_II_ITEM_6",
        }

        if item_number == "1" and normalized_title in title_to_part_i:
            return title_to_part_i[normalized_title]

        if item_number == "1" and normalized_title in title_to_part_ii:
            return title_to_part_ii[normalized_title]

        if (
            item_number in {"2", "3", "4"}
            and normalized_title in title_to_part_i
        ):
            return f"PART_I_ITEM_{item_number}"

        if item_number in {"1A", "2", "3", "4", "5", "6"}:
            candidate = f"PART_II_ITEM_{item_number}"

            if candidate in _build_taxonomy("10-Q"):
                return candidate

    return None


def _extract_sections_plain_text(
    document: SECFilingDocument,
    base_form: str,
) -> tuple[SECFilingSection, ...]:
    """
    Extract recognized sections from a plain-text filing.

    A recognized section begins at the beginning of its heading line and ends
    immediately before the next recognized Item heading. This preserves the
    complete heading as part of the evidence slice.
    """
    taxonomy = _build_taxonomy(base_form)
    candidates = _extract_heading_candidates(document.content, base_form)

    recognized: list[tuple[_HeadingCandidate, _TaxonomyEntry]] = []

    for candidate in candidates:
        section_key = _taxonomy_key(
            base_form,
            candidate.item_number,
            candidate.title,
        )

        if section_key is None:
            continue

        entry = taxonomy.get(section_key)

        if entry is None:
            continue

        recognized.append((candidate, entry))

    sections: list[SECFilingSection] = []
    occurrences: dict[str, int] = {}

    for index, (candidate, entry) in enumerate(recognized):
        next_start = (
            recognized[index + 1][0].start_offset
            if index + 1 < len(recognized)
            else len(document.content)
        )

        start_offset = candidate.start_offset
        end_offset = next_start

        section_id = entry.section_id
        occurrences[section_id] = occurrences.get(section_id, 0) + 1

        content = document.content[start_offset:end_offset]

        sections.append(
            SECFilingSection(
                filing=document.filing,
                document=document,
                section_id=section_id,
                section_title=entry.title,
                section_level=entry.level,
                occurrence=occurrences[section_id],
                start_offset=start_offset,
                end_offset=end_offset,
                content=content,
            )
        )

    return tuple(sections)


def extract_sections(
    document: SECFilingDocument,
) -> tuple[SECFilingSection, ...]:
    """
    Deterministically extract supported filing sections.

    SEC-5 first increment supports plain-text documents only.

    The raw HTML scanner introduced in SEC-5.2 is intentionally not invoked
    here yet. Integration will occur only after lxml structural interpretation
    has been explicitly mapped to authoritative raw-byte boundaries.

    Returns:
        Tuple of immutable SECFilingSection objects ordered by raw-byte
        start_offset.

    Raises:
        SECFilingFormatError:
            If the document is invalid, empty, or uses an unsupported form.
    """
    base_form = _validate_document(document)

    content_type = document.content_type.strip().lower()

    # The complete-submission SEC text endpoint commonly returns text/plain.
    # The first SEC-5 increment intentionally refuses HTML/inline-XBRL rather
    # than pretending that HTML parser offsets are raw-byte offsets.
    if "html" in content_type or "xml" in content_type:
        raise SECFilingFormatError(
            "HTML/XML extraction is not implemented in SEC-5 increment 1."
        )

    return _extract_sections_plain_text(document, base_form)