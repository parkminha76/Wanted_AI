from __future__ import annotations

import os
import tempfile
import unittest

from backend.scanner.masking import mask, policy
from backend.scanner.parser import locate, parse
from backend.shared.schema import Finding


def finding(risk_type: str, value: str, start: int = 0) -> Finding:
    return Finding(
        id="f_001",
        type=risk_type,
        text=value,
        start=start,
        end=start + len(value),
        confidence=1.0,
        source="rule",
        reason="test",
    )


class StandardMaskingTest(unittest.TestCase):
    def assert_standard(self, risk_type: str, value: str, expected: str) -> None:
        actual = policy.standard_mask(risk_type, value, "[FULL]")
        self.assertEqual(actual, expected)

    def test_standard_examples(self) -> None:
        self.assert_standard("person", "홍길동", "홍**")
        self.assert_standard("person", "HONG GILDONG", "HO** *******")
        self.assert_standard("birth_date", "1991-03-15", "1991-**-**")
        self.assert_standard("phone", "010-1234-5678", "010-1234-****")
        self.assert_standard("address", "서울시 영등포구 여의대로 123 4층", "서울시 영등포구 여의대로 ****")
        self.assert_standard("email", "na@abc.com", "n*@abc.com")
        self.assert_standard("email", "example@abc.com", "exa****@abc.com")
        self.assert_standard("rrn", "971225-1234567", "971225-1******")
        self.assert_standard("foreign_reg", "900101-5679427", "900101-5******")
        self.assert_standard("passport", "M12345678", "M12345***")
        self.assert_standard("account", "302-0654-1234-12", "302-065*-****-**")
        self.assert_standard("driver_license", "11-24-123456-78", "11-24-******-**")
        self.assert_standard("card", "4111-1111-1111-1111", "4111-****-****-1111")
        self.assert_standard("ip", "123.123.45.123", "123.123.***.123")

    def test_default_remains_full_and_rule_can_select_standard(self) -> None:
        item = finding("phone", "010-1234-5678")
        self.assertEqual(mask.build(item.text, [item]), "[전화번호]")
        selected = {"default": "full", "rules": {"phone": "standard"}}
        self.assertEqual(mask.build(item.text, [item], policy=selected), "010-1234-****")

    def test_unsupported_standard_fails_closed_to_full(self) -> None:
        item = finding("api_key", "sk-test-secret")
        selected = {"default": "standard", "rules": {}}
        self.assertEqual(mask.build(item.text, [item], policy=selected), "[API 키]")

    def test_invalid_policy_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            policy.normalize_policy({"default": "keep"})
        with self.assertRaises(ValueError):
            policy.normalize_policy({"rules": {"unknown_type": "standard"}})

    def test_per_finding_selection_masks_only_selected_items(self) -> None:
        phone = finding("phone", "010-1234-5678", 0)
        email = finding("email", "test@example.com", 14)
        rows = policy.normalize_selection(
            {
                "selections": [
                    {
                        "id": phone.id,
                        "type": phone.type,
                        "start": phone.start,
                        "end": phone.end,
                        "action": "standard",
                    }
                ]
            }
        )
        selected = policy.apply_selection([phone, email], rows)
        text = "010-1234-5678test@example.com"
        self.assertEqual(mask.build(text, selected), "010-1234-****test@example.com")
        with self.assertRaises(ValueError):
            policy.apply_selection([email], rows)

    def test_image_finding_selection_with_zero_offsets_is_accepted(self) -> None:
        """실측 버그(2026-09-17): 이미지 finding(text_ocr.py/id_detector.py)은
        문자 오프셋이 없어 start/end가 항상 0이라, 이 값을 그대로 선택 마스킹에
        보내면 `0 <= start < end`에 걸려 매번 422로 거부됐다 — 이미지 업로드는
        선택 마스킹 자체가 통째로 안 됐다는 뜻이다."""
        photo_person = finding("person", "이예지", 0)
        photo_person.end = 0  # 이미지 관례: start == end == 0
        rows = policy.normalize_selection(
            {
                "selections": [
                    {
                        "id": photo_person.id,
                        "type": photo_person.type,
                        "start": 0,
                        "end": 0,
                        "action": "full",
                    }
                ]
            }
        )
        selected = policy.apply_selection([photo_person], rows)
        self.assertEqual(len(selected), 1)

    def test_negative_or_inverted_offsets_are_still_rejected(self) -> None:
        with self.assertRaises(ValueError):
            policy.normalize_selection(
                {"selections": [{"id": "f_001", "type": "phone", "start": 5, "end": 2, "action": "full"}]}
            )
        with self.assertRaises(ValueError):
            policy.normalize_selection(
                {"selections": [{"id": "f_001", "type": "phone", "start": -1, "end": 3, "action": "full"}]}
            )

    def test_text_file_uses_selected_policy(self) -> None:
        value = "010-1234-5678"
        selected = {"default": "full", "rules": {"phone": "standard"}}
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "phone.txt")
            with open(source, "w", encoding="utf-8") as stream:
                stream.write(value)
            doc = parse.load(source)
            output = mask.build_file(
                source,
                doc,
                [finding("phone", value)],
                out_dir=os.path.join(temp_dir, "out"),
                policy=selected,
            )
            self.assertIsNotNone(output)
            with open(output, encoding="utf-8") as stream:
                self.assertEqual(stream.read(), "010-1234-****")

    def test_docx_xlsx_and_pdf_use_selected_policy(self) -> None:
        from docx import Document
        from openpyxl import Workbook, load_workbook
        import pymupdf

        value = "010-1234-5678"
        selected = {"default": "full", "rules": {"phone": "standard"}}
        with tempfile.TemporaryDirectory() as temp_dir:
            docx_path = os.path.join(temp_dir, "contact.docx")
            document = Document()
            document.add_paragraph(f"Contact {value}")
            document.save(docx_path)
            docx_doc = parse.load(docx_path)
            docx_start = docx_doc.raw_text.index(value)
            docx_output = mask.build_file(
                docx_path,
                docx_doc,
                [finding("phone", value, docx_start)],
                out_dir=os.path.join(temp_dir, "docx_out"),
                policy=selected,
            )
            self.assertIsNotNone(docx_output)
            docx_text = "\n".join(p.text for p in Document(docx_output).paragraphs)
            self.assertIn("010-1234-****", docx_text)

            xlsx_path = os.path.join(temp_dir, "contact.xlsx")
            workbook = Workbook()
            workbook.active["A1"] = f"Contact {value}"
            workbook.save(xlsx_path)
            xlsx_doc = parse.load(xlsx_path)
            xlsx_start = xlsx_doc.raw_text.index(value)
            xlsx_output = mask.build_file(
                xlsx_path,
                xlsx_doc,
                [finding("phone", value, xlsx_start)],
                out_dir=os.path.join(temp_dir, "xlsx_out"),
                policy=selected,
            )
            self.assertIsNotNone(xlsx_output)
            self.assertIn("010-1234-****", load_workbook(xlsx_output).active["A1"].value)

            pdf_path = os.path.join(temp_dir, "contact.pdf")
            pdf = pymupdf.open()
            page = pdf.new_page()
            page.insert_text((72, 72), f"Contact {value}")
            pdf.save(pdf_path)
            pdf.close()
            pdf_doc = parse.load(pdf_path)
            pdf_start = pdf_doc.raw_text.index(value)
            pdf_findings = [finding("phone", value, pdf_start)]
            locate.fill_coords(pdf_doc, pdf_findings)
            pdf_output = mask.build_file(
                pdf_path,
                pdf_doc,
                pdf_findings,
                out_dir=os.path.join(temp_dir, "pdf_out"),
                policy=selected,
            )
            self.assertIsNotNone(pdf_output)
            with pymupdf.open(pdf_output) as masked_pdf:
                self.assertIn("010-1234-****", "".join(p.get_text() for p in masked_pdf))


if __name__ == "__main__":
    unittest.main()

