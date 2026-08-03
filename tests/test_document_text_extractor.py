from __future__ import annotations

import zipfile
from io import BytesIO

from runtime.execution.misc.document_text_extractor import extract_document_text


def _archive(files: dict[str, str]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return buffer.getvalue()


def test_extracts_pptx_slides_in_numeric_order() -> None:
    data = _archive(
        {
            "ppt/slides/slide10.xml": '<p:sld xmlns:p="p" xmlns:a="a"><a:t>Ten</a:t></p:sld>',
            "ppt/slides/slide2.xml": '<p:sld xmlns:p="p" xmlns:a="a"><a:t>Two</a:t></p:sld>',
        }
    )
    result = extract_document_text(data, "pptx")
    assert result is not None
    assert result.text.index("Two") < result.text.index("Ten")


def test_extracts_docx_paragraphs() -> None:
    data = _archive(
        {
            "word/document.xml": (
                '<w:document xmlns:w="w"><w:body>'
                "<w:p><w:r><w:t>First paragraph</w:t></w:r></w:p>"
                "<w:p><w:r><w:t>Second paragraph</w:t></w:r></w:p>"
                "</w:body></w:document>"
            )
        }
    )
    result = extract_document_text(data, ".docx")
    assert result is not None
    assert result.text == "First paragraph\nSecond paragraph"


def test_extracts_xlsx_shared_and_inline_strings() -> None:
    data = _archive(
        {
            "xl/sharedStrings.xml": (
                '<sst xmlns="x"><si><t>Name</t></si><si><t>Ada</t></si></sst>'
            ),
            "xl/worksheets/sheet1.xml": (
                '<worksheet xmlns="x"><sheetData><row>'
                '<c t="s"><v>0</v></c><c t="inlineStr"><is><t>Score</t></is></c>'
                '</row><row><c t="s"><v>1</v></c><c><v>98</v></c></row>'
                "</sheetData></worksheet>"
            ),
        }
    )
    result = extract_document_text(data, "xlsx")
    assert result is not None
    assert "Name\tScore" in result.text
    assert "Ada\t98" in result.text


def test_truncates_with_read_file_hint() -> None:
    result = extract_document_text(b"x" * 200, "txt", max_chars=20)
    assert result is not None
    assert result.truncated is True
    assert result.text.startswith("x" * 20)
    assert "use read_file" in result.text


def test_rejects_unknown_binary_format() -> None:
    assert extract_document_text(b"binary", "exe") is None
