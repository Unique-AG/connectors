"""Generate the seed's binary files from corpus values with the standard library only.

Every timestamp inside a file is a constant, so the same corpus gives the same bytes and the
same SHA-256 on every run and every day.
"""

import io
import zipfile
from xml.sax.saxutils import escape

FIXED_ZIP_TIME = (2026, 1, 5, 9, 0, 0)
FIXED_W3CDTF = "2026-01-05T09:00:00Z"
FIXED_PDF_DATE = "D:20260105090000Z"
GENERATOR = "seed-v1 generator"

RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
XML_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


def _zip(parts: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in parts.items():
            info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, text.encode("utf-8"))
    return buffer.getvalue()


def _core(props: dict[str, str]) -> str:
    return (
        XML_HEAD
        + '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"'
        ' xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/"'
        ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<dc:title>{escape(props.get('title', ''))}</dc:title>"
        f"<dc:creator>{escape(props.get('creator', ''))}</dc:creator>"
        f"<cp:lastModifiedBy>{escape(props.get('last_modified_by', ''))}</cp:lastModifiedBy>"
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{FIXED_W3CDTF}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{FIXED_W3CDTF}</dcterms:modified>'
        "</cp:coreProperties>"
    )


def _app(props: dict[str, str]) -> str:
    return (
        XML_HEAD
        + '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
        f"<Application>{GENERATOR}</Application><Company>{escape(props.get('company', ''))}</Company>"
        "</Properties>"
    )


def _package_rels(main_part: str) -> str:
    return (
        XML_HEAD + f'<Relationships xmlns="{RELS_NS}">'
        f'<Relationship Id="rId1" Type="{OFFICE_REL}/officeDocument" Target="{main_part}"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/'
        'metadata/core-properties" Target="docProps/core.xml"/>'
        f'<Relationship Id="rId3" Type="{OFFICE_REL}/extended-properties" Target="docProps/app.xml"/>'
        "</Relationships>"
    )


def _content_types(overrides: dict[str, str]) -> str:
    body = "".join(f'<Override PartName="{p}" ContentType="{t}"/>' for p, t in overrides.items())
    return (
        XML_HEAD + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f"{body}</Types>"
    )


PROPS_TYPES = {
    "/docProps/core.xml": "application/vnd.openxmlformats-package.core-properties+xml",
    "/docProps/app.xml": "application/vnd.openxmlformats-officedocument.extended-properties+xml",
}


def docx(paragraphs: list[str], props: dict[str, str]) -> bytes:
    runs = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{escape(p)}</w:t></w:r></w:p>' for p in paragraphs
    )
    document = (
        XML_HEAD
        + '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{runs}</w:body></w:document>"
    )
    main = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
    return _zip(
        {
            "[Content_Types].xml": _content_types({"/word/document.xml": main, **PROPS_TYPES}),
            "_rels/.rels": _package_rels("word/document.xml"),
            "word/document.xml": document,
            "docProps/core.xml": _core(props),
            "docProps/app.xml": _app(props),
        }
    )


def _column(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        name = chr(65 + rest) + name
    return name


def _cell(ref: str, value: str) -> str:
    if value.isdigit():
        return f'<c r="{ref}"><v>{value}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'


def xlsx(rows: list[list[str]], props: dict[str, str]) -> bytes:
    sheet_rows = "".join(
        f'<row r="{r + 1}">'
        + "".join(_cell(f"{_column(c)}{r + 1}", str(v)) for c, v in enumerate(row))
        + "</row>"
        for r, row in enumerate(rows)
    )
    sheet = (
        XML_HEAD + '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{sheet_rows}</sheetData></worksheet>"
    )
    workbook = (
        XML_HEAD + '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        f' xmlns:r="{OFFICE_REL}"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    workbook_rels = (
        XML_HEAD + f'<Relationships xmlns="{RELS_NS}">'
        f'<Relationship Id="rId1" Type="{OFFICE_REL}/worksheet" Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )
    sml = "application/vnd.openxmlformats-officedocument.spreadsheetml"
    return _zip(
        {
            "[Content_Types].xml": _content_types(
                {
                    "/xl/workbook.xml": f"{sml}.sheet.main+xml",
                    "/xl/worksheets/sheet1.xml": f"{sml}.worksheet+xml",
                    **PROPS_TYPES,
                }
            ),
            "_rels/.rels": _package_rels("xl/workbook.xml"),
            "xl/workbook.xml": workbook,
            "xl/_rels/workbook.xml.rels": workbook_rels,
            "xl/worksheets/sheet1.xml": sheet,
            "docProps/core.xml": _core(props),
            "docProps/app.xml": _app(props),
        }
    )


def _pdf_text(value: str) -> str:
    return "(" + value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ")"


def pdf(lines: list[str], props: dict[str, str]) -> bytes:
    text_ops = (
        "BT /F1 14 Tf 72 770 Td " + " 0 -22 Td ".join(f"{_pdf_text(x)} Tj" for x in lines) + " ET"
    )
    stream = text_ops.encode("latin-1")
    info = (
        f"<< /Title {_pdf_text(props.get('title', ''))} /Author {_pdf_text(props.get('creator', ''))}"
        f" /Company {_pdf_text(props.get('company', ''))} /Creator {_pdf_text(GENERATOR)}"
        f" /Producer {_pdf_text(GENERATOR)} /CreationDate {_pdf_text(FIXED_PDF_DATE)} >>"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        info.encode("latin-1"),
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + obj + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R /Info 6 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref_at,
    )
    return bytes(out)
