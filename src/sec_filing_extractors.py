"""
Deterministic SEC filing section extraction.

SEC-5 responsibilities:
    - Defines the immutable SECFilingSection evidence contract.
    - Defines filing-type-aware deterministic section taxonomies.
    - Supports plain-text SEC filing extraction.
    - Supports deterministic HTML / inline-XBRL section extraction.
    - Preserves exact raw-byte section boundaries.
    - Uses the original filing bytes as the authoritative evidence source.
    - Does not perform financial interpretation or LLM-based extraction.

Important source-position contract:

    section.content == document.content[
        section.start_offset : section.end_offset
    ]

HTML parsers are used only for structural interpretation when needed.
Parser-normalized text, decoded entities, or parser-generated offsets are
never treated as authoritative evidence locations.
"""

from __future__ import annotations

import html
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


_SUPPORTED_FORMS: Final[frozenset[str]] = frozenset({"10-K", "10-Q", "8-K"})


# ---------------------------------------------------------------------------
# Raw HTML source-position scanning
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _RawHTMLToken:
    """
    Immutable representation of one raw HTML lexical token.

    Offsets are byte offsets into the original filing bytes.
    The end offset is exclusive.
    """

    token_type: str
    start_offset: int
    end_offset: int
    tag_name: Optional[bytes] = None


_HTML_TAG_NAME_CHARS = frozenset(
    b"abcdefghijklmnopqrstuvwxyz"
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    b"0123456789"
    b":_-"
)

_HTML_VOID_ELEMENTS: Final[frozenset[bytes]] = frozenset(
    {
        b"area",
        b"base",
        b"br",
        b"col",
        b"embed",
        b"hr",
        b"img",
        b"input",
        b"link",
        b"meta",
        b"param",
        b"source",
        b"track",
        b"wbr",
    }
)

_HTML_BLOCK_ELEMENTS: Final[frozenset[bytes]] = frozenset(
    {
        b"address",
        b"article",
        b"aside",
        b"blockquote",
        b"body",
        b"caption",
        b"dd",
        b"div",
        b"dl",
        b"dt",
        b"fieldset",
        b"figcaption",
        b"figure",
        b"footer",
        b"form",
        b"h1",
        b"h2",
        b"h3",
        b"h4",
        b"h5",
        b"h6",
        b"header",
        b"li",
        b"main",
        b"nav",
        b"ol",
        b"p",
        b"pre",
        b"section",
        b"table",
        b"tbody",
        b"td",
        b"tfoot",
        b"th",
        b"thead",
        b"tr",
        b"ul",
    }
)


def _is_html_tag_name_start(value: int) -> bool:
    """Return whether a byte can begin an HTML tag name."""
    return 65 <= value <= 90 or 97 <= value <= 122


def _is_html_tag_name_byte(value: int) -> bool:
    """Return whether a byte can occur inside an HTML tag name."""
    return value in _HTML_TAG_NAME_CHARS


def _find_tag_end(content: bytes, start_offset: int) -> int:
    """
    Find the exclusive end of an HTML tag while respecting quoted attributes.

    A '>' inside a quoted attribute does not terminate the tag.
    """
    quote: Optional[int] = None
    index = start_offset + 1
    length = len(content)

    while index < length:
        current = content[index]

        if quote is not None:
            if current == quote:
                quote = None
        elif current in (34, 39):
            quote = current
        elif current == 62:
            return index + 1

        index += 1

    raise SECFilingFormatError(
        "Unterminated HTML tag encountered while scanning raw filing content."
    )


def _find_comment_end(content: bytes, start_offset: int) -> int:
    """Find the exclusive end of an HTML comment."""
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
    """Find the exclusive end of an XML processing instruction."""
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
    """Extract a lowercase ASCII tag name from a raw tag token."""
    index = start_offset + 1

    if index < end_offset and content[index] == 47:
        index += 1

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
    """
    Scan original HTML bytes into deterministic lexical tokens.

    The scanner never decodes or rewrites the source. Every offset therefore
    refers directly to the original raw byte sequence.
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
        if content[index] != 60:
            index += 1
            continue

        if text_start < index:
            tokens.append(
                _RawHTMLToken(
                    token_type="text",
                    start_offset=text_start,
                    end_offset=index,
                )
            )

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
# Raw HTML structural interpretation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _RawHTMLElement:
    """
    Internal representation of an HTML element reconstructed from raw tokens.

    Offsets always refer to the original document bytes.
    """

    tag_name: bytes
    start_offset: int
    end_offset: int
    child_indexes: tuple[int, ...]


def _is_self_closing_start_tag(
    content: bytes,
    token: _RawHTMLToken,
) -> bool:
    """Return whether a raw start tag ends with '/>'."""
    if token.token_type != "start_tag":
        return False

    tag_content = content[token.start_offset:token.end_offset].rstrip()

    return tag_content.endswith(b"/>") or token.tag_name in _HTML_VOID_ELEMENTS


def _build_raw_html_elements(
    content: bytes,
    tokens: tuple[_RawHTMLToken, ...],
) -> tuple[_RawHTMLElement, ...]:
    """
    Reconstruct a tolerant element tree from raw HTML tokens.

    This is intentionally not a standards-complete HTML parser. Its purpose
    is limited to recovering source ranges and parent/child relationships
    needed for deterministic heading recognition.

    Malformed end tags are tolerated where possible because SEC filings may
    contain imperfect issuer-generated HTML.
    """
    elements: list[_RawHTMLElement] = []
    mutable_children: list[list[int]] = []
    stack: list[int] = []

    for token in tokens:
        if token.token_type == "start_tag":
            if token.tag_name is None:
                continue

            element_index = len(elements)

            elements.append(
                _RawHTMLElement(
                    tag_name=token.tag_name,
                    start_offset=token.start_offset,
                    end_offset=token.end_offset,
                    child_indexes=(),
                )
            )
            mutable_children.append([])

            if stack:
                mutable_children[stack[-1]].append(element_index)

            if not _is_self_closing_start_tag(content, token):
                stack.append(element_index)

        elif token.token_type == "end_tag":
            if token.tag_name is None:
                continue

            matching_position: Optional[int] = None

            for position in range(len(stack) - 1, -1, -1):
                if elements[stack[position]].tag_name == token.tag_name:
                    matching_position = position
                    break

            if matching_position is None:
                continue

            element_index = stack[matching_position]

            elements[element_index] = _RawHTMLElement(
                tag_name=elements[element_index].tag_name,
                start_offset=elements[element_index].start_offset,
                end_offset=token.end_offset,
                child_indexes=tuple(mutable_children[element_index]),
            )

            del stack[matching_position:]

    for element_index in stack:
        elements[element_index] = _RawHTMLElement(
            tag_name=elements[element_index].tag_name,
            start_offset=elements[element_index].start_offset,
            end_offset=len(content),
            child_indexes=tuple(mutable_children[element_index]),
        )

    return tuple(elements)


def _element_text(
    content: bytes,
    tokens: tuple[_RawHTMLToken, ...],
    element: _RawHTMLElement,
) -> str:
    """
    Recover human-readable text contained by an element.

    Entity decoding occurs only in this temporary structural representation.
    The original bytes remain untouched and authoritative.
    """
    pieces: list[str] = []

    for token in tokens:
        if token.start_offset < element.start_offset:
            continue

        if token.end_offset > element.end_offset:
            break

        if token.token_type != "text":
            continue

        raw_text = content[token.start_offset:token.end_offset]

        try:
            decoded = raw_text.decode("utf-8")
        except UnicodeDecodeError:
            decoded = raw_text.decode("latin-1")

        pieces.append(decoded)

    return html.unescape(" ".join(pieces))


def _is_heading_like_element(tag_name: bytes) -> bool:
    """
    Return whether an element is a plausible filing heading container.

    Standard heading tags are preferred. Common block-level SEC-generated
    containers are also inspected because many filings represent headings
    with div/p/td/span combinations rather than semantic h1-h6 tags.
    """
    return tag_name in _HTML_BLOCK_ELEMENTS or tag_name in {
        b"title",
        b"span",
    }


def _extract_heading_candidates_html(
    content: bytes,
    base_form: str,
) -> tuple[_HeadingCandidate, ...]:
    """
    Identify SEC Item headings from raw HTML structure.

    Candidate boundaries are taken from the raw element ranges, never from
    parser-generated character offsets.
    """
    del base_form  # Reserved for future filing-specific HTML rules.

    tokens = _scan_raw_html(content)
    elements = _build_raw_html_elements(content, tokens)

    candidates: list[_HeadingCandidate] = []

    for element in elements:
        if not _is_heading_like_element(element.tag_name):
            continue

        text = _element_text(content, tokens, element)

        # Collapse HTML whitespace, including Unicode whitespace such as
        # U+2009 THIN SPACE used by some real SEC filings.
        text = re.sub(r"\s+", " ", text).strip()

        if not text or len(text) > 500:
            continue

        match = _ITEM_HEADING_PATTERN.match(text)

        if not match:
            continue

        number = match.group("number")
        letter = match.group("letter") or ""
        item_number = f"{number}{letter}".upper()
        title = match.group("title").strip()

        if not title:
            continue

        if element.tag_name not in {
            b"h1",
            b"h2",
            b"h3",
            b"h4",
            b"h5",
            b"h6",
        }:
            nested_heading_exists = False

            for child_index in element.child_indexes:
                child = elements[child_index]

                if child.tag_name not in {
                    b"h1",
                    b"h2",
                    b"h3",
                    b"h4",
                    b"h5",
                    b"h6",
                }:
                    continue

                child_text = re.sub(
                    r"\s+",
                    " ",
                    _element_text(content, tokens, child),
                ).strip()

                if _ITEM_HEADING_PATTERN.match(child_text):
                    nested_heading_exists = True
                    break

            if nested_heading_exists:
                continue

        candidates.append(
            _HeadingCandidate(
                item_number=item_number,
                title=title,
                start_offset=element.start_offset,
                end_offset=element.end_offset,
            )
        )

    deduplicated: list[_HeadingCandidate] = []
    seen: set[tuple[int, str, str]] = set()

    for candidate in sorted(
        candidates,
        key=lambda item: (
            item.start_offset,
            item.end_offset,
            item.item_number,
            item.title.casefold(),
        ),
    ):
        identity = (
            candidate.start_offset,
            candidate.item_number,
            _normalize_title(candidate.title),
        )

        if identity in seen:
            continue

        seen.add(identity)
        deduplicated.append(candidate)

    return tuple(deduplicated)


# ---------------------------------------------------------------------------
# Filing section taxonomy
# ---------------------------------------------------------------------------


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
        ("ITEM_1_02", "Termination of a Material Definitive Agreement", 1),
        ("ITEM_1_03", "Bankruptcy or Receivership", 1),
        ("ITEM_1_04", "Mine Safety Reporting", 1),
        ("ITEM_1_05", "Material Cybersecurity Incidents", 1),
        ("ITEM_2_01", "Completion of Acquisition or Disposition of Assets", 1),
        ("ITEM_2_02", "Results of Operations and Financial Condition", 1),
        ("ITEM_2_03", "Creation of a Direct Financial Obligation", 1),
        (
            "ITEM_2_04",
            "Triggering Events That Accelerate or Increase "
            "a Direct Financial Obligation",
            1,
        ),
        ("ITEM_2_05", "Costs Associated With Exit or Disposal Activities", 1),
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
        ("ITEM_5_02", "Departure of Directors or Certain Officers", 1),
        ("ITEM_5_03", "Amendments to Articles of Incorporation or Bylaws", 1),
        ("ITEM_5_04", "Temporary Suspension of Trading", 1),
        ("ITEM_5_05", "Amendment to Registrant's Code of Ethics", 1),
        ("ITEM_5_06", "Change in Shell Company Status", 1),
        ("ITEM_5_07", "Submission of Matters to a Vote", 1),
        ("ITEM_5_08", "Shareholder Director Nominations", 1),
        ("ITEM_6_01", "ABS Informational and Computational Material", 1),
        ("ITEM_6_02", "Change of Servicer or Trustee", 1),
        ("ITEM_6_03", "Change in Credit Enhancement", 1),
        ("ITEM_6_04", "Failure to Make a Required Distribution", 1),
        ("ITEM_6_05", "Securities Act Updating Disclosure", 1),
        ("ITEM_7_01", "Regulation FD Disclosure", 1),
        ("ITEM_8_01", "Other Events", 1),
        ("ITEM_9_01", "Financial Statements and Exhibits", 1),
    ),
}


# ---------------------------------------------------------------------------
# Heading recognition
# ---------------------------------------------------------------------------


# SEC 8-K item numbers contain a decimal component, e.g. 7.01 and 9.01.
# The decimal component must therefore be captured as part of the item
# number rather than interpreted as punctuation preceding the title.
_ITEM_HEADING_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[ \t]*ITEM[ \t]+"
    r"(?P<number>\d+(?:\.\d+)?)"
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

    and refer directly to the original raw bytes.
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

        if self.end_offset > len(self.document.content):
            raise SECFilingSectionError(
                "Section end_offset exceeds the document content length."
            )

        expected_content = self.document.content[
            self.start_offset:self.end_offset
        ]

        if self.content != expected_content:
            raise SECFilingSectionError(
                "content must exactly equal the corresponding raw document slice."
            )


@dataclass(frozen=True)
class _HeadingCandidate:
    """Internal immutable representation of a recognized filing heading."""

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
    """Return the base SEC form, removing an amendment suffix."""
    if not isinstance(form, str) or not form.strip():
        raise SECFilingFormatError("Filing form must be a non-empty string.")

    normalized = form.strip().upper()

    if normalized.endswith("/A"):
        normalized = normalized[:-2]

    return normalized


def _validate_document(document: SECFilingDocument) -> str:
    """Validate the filing document and return its supported base form."""
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
    """Decode filing bytes for parsing while preserving raw bytes separately."""
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("latin-1")


def _line_start_offsets(content: bytes) -> tuple[int, ...]:
    """Return raw-byte offsets for the beginning of every text line."""
    offsets = [0]

    for match in re.finditer(b"\n", content):
        offsets.append(match.end())

    return tuple(offsets)


def _normalize_title(title: str) -> str:
    """Normalize heading text for deterministic taxonomy matching."""
    normalized = re.sub(r"\s+", " ", title.strip())
    normalized = normalized.strip(" .:-–—\t")
    return normalized.casefold()


def _extract_heading_candidates(
    content: bytes,
    base_form: str,
) -> tuple[_HeadingCandidate, ...]:
    """Identify structurally plausible Item headings in plain-text content."""
    del base_form  # Reserved for future filing-specific plain-text rules.

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

            raw_line = content[
                start_offset:
                content.find(b"\n", start_offset) + 1
                if content.find(b"\n", start_offset) >= 0
                else len(content)
            ]

            end_offset = start_offset + len(raw_line)

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
    """Build the filing-specific deterministic taxonomy lookup."""
    return {
        section_id: _TaxonomyEntry(
            section_id=section_id,
            title=title,
            level=level,
        )
        for section_id, title, level in _SECTION_TAXONOMY[base_form]
    }


def _taxonomy_key(
    base_form: str,
    item_number: str,
    title: str,
) -> str | None:
    """Resolve an Item heading to the deterministic filing taxonomy."""
    normalized_title = _normalize_title(title)

    if base_form == "10-K":
        return f"ITEM_{item_number}"

    if base_form == "8-K":
        return f"ITEM_{item_number.replace('.', '_')}"

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

        if item_number in {"2", "3", "4"} and normalized_title in title_to_part_i:
            return f"PART_I_ITEM_{item_number}"

        if item_number in {"1A", "2", "3", "4", "5", "6"}:
            candidate = f"PART_II_ITEM_{item_number}"

            if candidate in _build_taxonomy("10-Q"):
                return candidate

    return None


def _extract_sections_from_candidates(
    document: SECFilingDocument,
    base_form: str,
    candidates: tuple[_HeadingCandidate, ...],
) -> tuple[SECFilingSection, ...]:
    """
    Convert recognized heading candidates into immutable evidence sections.
    """
    taxonomy = _build_taxonomy(base_form)

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

    recognized.sort(
        key=lambda pair: (
            pair[0].start_offset,
            pair[0].end_offset,
            pair[0].item_number,
        )
    )

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

        if end_offset < start_offset:
            raise SECFilingSectionError(
                "Section boundaries are not monotonically ordered."
            )

        section_id = entry.section_id
        occurrences[section_id] = occurrences.get(section_id, 0) + 1

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
                content=document.content[start_offset:end_offset],
            )
        )

    return tuple(sections)


def _extract_sections_plain_text(
    document: SECFilingDocument,
    base_form: str,
) -> tuple[SECFilingSection, ...]:
    """Extract recognized sections from a plain-text filing."""
    candidates = _extract_heading_candidates(
        document.content,
        base_form,
    )

    return _extract_sections_from_candidates(
        document,
        base_form,
        candidates,
    )


def _extract_sections_html(
    document: SECFilingDocument,
    base_form: str,
) -> tuple[SECFilingSection, ...]:
    """
    Extract recognized sections from HTML / inline-XBRL content.

    The raw scanner establishes source boundaries. HTML structure is used only
    to identify likely heading containers and reconstruct their text.
    """
    candidates = _extract_heading_candidates_html(
        document.content,
        base_form,
    )

    return _extract_sections_from_candidates(
        document,
        base_form,
        candidates,
    )


def extract_sections(
    document: SECFilingDocument,
) -> tuple[SECFilingSection, ...]:
    """
    Deterministically extract supported SEC filing sections.

    Plain-text and HTML/XML SEC filing representations are supported.

    For HTML/XML:
        - raw bytes remain authoritative;
        - structural interpretation is performed from raw tokens;
        - entity decoding is parsing-only;
        - section offsets always reference original raw bytes.

    Missing recognized sections are normal and return no section for that
    taxonomy entry.

    Returns:
        Immutable SECFilingSection objects ordered by source offset.

    Raises:
        SECFilingFormatError:
            If the document is invalid, empty, unsupported, or malformed.
    """
    base_form = _validate_document(document)
    content_type = document.content_type.strip().lower()

    if "html" in content_type or "xml" in content_type:
        return _extract_sections_html(document, base_form)

    return _extract_sections_plain_text(document, base_form)