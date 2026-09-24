"""Independent synthetic contract tests for analog-recovery v0.2.

The fixtures in this file are deliberately self-contained.  They do not open
project netlists, reports, prior run outputs, or any FM377 artifact.
"""

import copy
import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_validator(relative_path: str, module_name: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load validator: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validate


validate_protocol = _load_validator(
    "skills/analog-recovery-evidence/scripts/check_protocol.py", "recovery_v02_protocol"
)
validate_docx = _load_validator(
    "skills/analog-recovery-report/scripts/check_docx.py", "recovery_v02_docx"
)


def _measurement(mid="vout", *, quantity="voltage", domain="output", classification="SIMULATED", method="dc sample"):
    return {
        "id": mid,
        "quantity": quantity,
        "definition": "output value at the declared operating point",
        "domain": domain,
        "source_terms": ["V(VOUT)"],
        "excludes": [],
        "classification": classification,
        "method": method,
    }


def _run(rid="dc", *, status="valid", runtime=1.0, completed=True, exit_code=0,
         warnings=None, limitations=None, saved=None, required=None, derived=None,
         analysis="dc", claim_scope="operating_point"):
    return {
        "id": rid,
        "exit_code": exit_code,
        "completed": completed,
        "runtime_s": runtime,
        "status": status,
        "warnings": list(warnings or []),
        "limitations": list(limitations or []),
        "saved_signals": list(saved or ["V(VOUT)"]),
        "required_signals": list(required or []),
        "derived_signals": list(derived or []),
        "analysis": analysis,
        "claim_scope": claim_scope,
    }


def _protocol():
    return {
        "version": "0.2",
        "scope": "standalone",
        "boundary": [
            {"port": "VIN", "state": "driven", "source": "tb.vin", "compliance": "0..1V", "role_basis": "input source"},
            {"port": "VOUT", "state": "observed", "source": "", "compliance": "", "role_basis": "output observation"},
            {"port": "VSS", "state": "disconnected", "source": "", "compliance": "", "role_basis": "unconnected by contract"},
        ],
        "measurements": [_measurement()],
        "runs": [_run()],
        "budget_s": 2.0,
        "max_parallel": 1,
        "clarification": {"blocking": [], "assumptions": ["VIN is a driven testbench source"]},
    }


def _assert_valid(testcase, result):
    testcase.assertTrue(result["valid"], result.get("errors"))


def _assert_invalid(testcase, result):
    testcase.assertFalse(result["valid"], result.get("errors"))
    testcase.assertTrue(result.get("errors"), "invalid results must explain the rejection")


class ProtocolV02Tests(unittest.TestCase):
    def test_valid_standalone_contract(self):
        _assert_valid(self, validate_protocol(_protocol()))

    def test_duplicate_port_run_and_measurement_ids_are_rejected(self):
        for area in ("boundary", "runs", "measurements"):
            with self.subTest(area=area):
                protocol = _protocol()
                protocol[area].append(copy.deepcopy(protocol[area][0]))
                _assert_invalid(self, validate_protocol(protocol))

    def test_runtime_must_be_finite_nonnegative_and_within_budget(self):
        for runtime in (-0.1, float("inf"), float("nan")):
            with self.subTest(runtime=runtime):
                protocol = _protocol()
                protocol["runs"][0]["runtime_s"] = runtime
                _assert_invalid(self, validate_protocol(protocol))

        protocol = _protocol()
        protocol["runs"].append(_run("hold", runtime=1.1))
        _assert_invalid(self, validate_protocol(protocol))

    def test_warning_requires_qualification_but_qualified_run_can_explain_limitations(self):
        protocol = _protocol()
        protocol["runs"][0]["warnings"] = ["reduced timestep"]
        _assert_invalid(self, validate_protocol(protocol))

        protocol["runs"][0]["status"] = "qualified"
        protocol["runs"][0]["limitations"] = ["settling was not measured"]
        _assert_valid(self, validate_protocol(protocol))

    def test_missing_required_signal_needs_a_saved_input_or_derivation(self):
        protocol = _protocol()
        protocol["runs"][0]["required_signals"] = ["I(VLOAD)"]
        protocol["runs"][0]["saved_signals"] = ["V(VOUT)"]
        _assert_invalid(self, validate_protocol(protocol))

        protocol["runs"][0]["saved_signals"] = ["V(VOUT)", "I(VLOAD)"]
        protocol["runs"][0]["required_signals"] = ["PLOAD"]
        protocol["runs"][0]["derived_signals"] = [{
            "name": "PLOAD",
            "method": "V(VOUT) * I(VLOAD)",
            "inputs": ["V(VOUT)", "I(VLOAD)"],
        }]
        _assert_valid(self, validate_protocol(protocol))

    def test_planned_cannot_claim_completion_or_measured_runtime(self):
        protocol = _protocol()
        protocol["runs"][0].update({"status": "planned", "completed": True, "runtime_s": 0.3})
        _assert_invalid(self, validate_protocol(protocol))

        protocol["runs"][0].update({"status": "planned", "completed": False, "runtime_s": None, "exit_code": None})
        _assert_valid(self, validate_protocol(protocol))

    def test_failed_run_is_allowed_but_its_elapsed_time_counts_toward_budget(self):
        protocol = _protocol()
        protocol["runs"][0].update({"status": "failed", "completed": False, "exit_code": 1, "runtime_s": 1.5})
        _assert_valid(self, validate_protocol(protocol))
        protocol["budget_s"] = 1.0
        _assert_invalid(self, validate_protocol(protocol))

    def test_hold_claim_cannot_be_labeled_startup(self):
        protocol = _protocol()
        protocol["runs"][0].update({"analysis": "hold", "claim_scope": "startup"})
        _assert_invalid(self, validate_protocol(protocol))

    def test_derived_measurement_requires_method_and_mixed_domain_current_is_rejected(self):
        protocol = _protocol()
        protocol["measurements"][0].update({"classification": "DERIVED", "method": ""})
        _assert_invalid(self, validate_protocol(protocol))

        protocol = _protocol()
        protocol["measurements"][0].update({"quantity": "current", "domain": "mixed"})
        _assert_invalid(self, validate_protocol(protocol))

    def test_disconnected_boundary_port_cannot_have_a_source(self):
        protocol = _protocol()
        protocol["boundary"][2]["source"] = "tb.vss"
        _assert_invalid(self, validate_protocol(protocol))

    def test_saved_signals_must_be_a_string_array(self):
        protocol = _protocol()
        protocol["runs"][0]["saved_signals"] = "V(VOUT)"
        _assert_invalid(self, validate_protocol(protocol))


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _p(text, *, num_id=None, style=None):
    ppr = []
    if style:
        ppr.append(f'<w:pStyle w:val="{style}"/>')
    if num_id is not None:
        ppr.append(f'<w:numPr><w:ilvl w:val="0"/><w:numId w:val="{num_id}"/></w:numPr>')
    prefix = f"<w:pPr>{''.join(ppr)}</w:pPr>" if ppr else ""
    return f'<w:p>{prefix}<w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


def _document_xml(paragraphs):
    body = "".join(paragraphs) + "<w:sectPr/>"
    return f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'


def _numbering_xml(*, abstract_id, num_id, bullet=True):
    if bullet:
        lvl = '<w:numFmt w:val="bullet"/><w:lvlText w:val="&#xf0b7;"/><w:rPr><w:rFonts w:ascii="Symbol" w:hAnsi="Symbol"/></w:rPr>'
    else:
        lvl = '<w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/>'
    return (
        f'<w:numbering xmlns:w="{W}"><w:abstractNum w:abstractNumId="{abstract_id}">'
        f'<w:lvl w:ilvl="0">{lvl}</w:lvl></w:abstractNum>'
        f'<w:num w:numId="{num_id}"><w:abstractNumId w:val="{abstract_id}"/></w:num></w:numbering>'
    )


def _write_docx(path, paragraphs, *, abstract_id=1, bullet_num_id=10, extra_numbering=False):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"/>")
        archive.writestr("word/document.xml", _document_xml(paragraphs))
        numbering = _numbering_xml(abstract_id=abstract_id, num_id=bullet_num_id)
        if extra_numbering:
            numbering = numbering.replace("</w:numbering>", f'<w:abstractNum w:abstractNumId="77"><w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl></w:abstractNum><w:num w:numId="77"><w:abstractNumId w:val="77"/></w:num></w:numbering>')
        archive.writestr("word/numbering.xml", numbering)


def _doc_paragraphs(*, native_num=20, manual=False, numbered_label=False, numbered_method=False):
    bullet = _p("* 手写说明") if manual else _p("功能示例", num_id=native_num)
    label_num = 77 if numbered_label else None
    method_text = "（1）仿真方法：dc" if numbered_method else "仿真方法：dc"
    return [
        _p("功能"), bullet, _p("特性"), _p("指标"),
        _p("验证"), _p("仿真工具：tool", num_id=label_num), _p("仿真路径：path"),
        _p(method_text), _p("结果分析：ok"), _p("结束"), _p("其它编号段落", num_id=77),
    ]


def _profile():
    return {
        "bullet_sections": [{"start": "功能", "end": "指标", "skip": ["特性"], "template_example": "功能示例"}],
        "label_sections": [{"start": "验证", "end": "结束", "labels": ["仿真工具", "仿真路径", "仿真方法", "结果分析"]}],
    }


class DocxV02Tests(unittest.TestCase):
    def _fixture(self, *, manual=False, numbered_label=False, numbered_method=False, missing_section=False,
                 missing_example=False, duplicate_template=False, document_missing_start=False,
                 document_missing_end=False):
        profile = _profile()
        template_paragraphs = _doc_paragraphs(native_num=10)
        document_paragraphs = _doc_paragraphs(
            native_num=20,
            manual=manual,
            numbered_label=numbered_label,
            numbered_method=numbered_method,
        )
        if missing_section:
            template_paragraphs = [_p("别的章节")]
        if missing_example:
            template_paragraphs[1] = _p("不同示例", num_id=10)
        if duplicate_template:
            template_paragraphs.insert(2, _p("功能示例", num_id=10))
        if document_missing_start:
            document_paragraphs = [p for i, p in enumerate(document_paragraphs) if i != 0]
        if document_missing_end:
            document_paragraphs = [p for i, p in enumerate(document_paragraphs) if i != 9]
        tmp = tempfile.TemporaryDirectory()
        template = Path(tmp.name) / "template.docx"
        document = Path(tmp.name) / "document.docx"
        _write_docx(template, template_paragraphs, abstract_id=1, bullet_num_id=10, extra_numbering=True)
        _write_docx(document, document_paragraphs, abstract_id=9, bullet_num_id=20, extra_numbering=True)
        return tmp, template, document, profile

    def test_native_bullet_passes_when_num_ids_differ_but_symbol_and_font_match(self):
        tmp, template, document, profile = self._fixture()
        self.addCleanup(tmp.cleanup)
        _assert_valid(self, validate_docx(str(template), str(document), profile))

    def test_handwritten_star_is_not_a_native_bullet(self):
        tmp, template, document, profile = self._fixture(manual=True)
        self.addCleanup(tmp.cleanup)
        _assert_invalid(self, validate_docx(str(template), str(document), profile))

    def test_numbered_fixed_label_is_rejected(self):
        tmp, template, document, profile = self._fixture(numbered_label=True)
        self.addCleanup(tmp.cleanup)
        _assert_invalid(self, validate_docx(str(template), str(document), profile))

    def test_handwritten_parenthesized_number_on_fixed_label_is_rejected(self):
        tmp, template, document, profile = self._fixture(numbered_method=True)
        self.addCleanup(tmp.cleanup)
        _assert_invalid(self, validate_docx(str(template), str(document), profile))

    def test_missing_section_and_missing_template_example_are_rejected(self):
        for kwargs in ({"missing_section": True}, {"missing_example": True}):
            with self.subTest(kwargs=kwargs):
                tmp, template, document, profile = self._fixture(**kwargs)
                self.addCleanup(tmp.cleanup)
                _assert_invalid(self, validate_docx(str(template), str(document), profile))

    def test_document_missing_start_or_end_is_rejected(self):
        for kwargs in ({"document_missing_start": True}, {"document_missing_end": True}):
            with self.subTest(kwargs=kwargs):
                tmp, template, document, profile = self._fixture(**kwargs)
                self.addCleanup(tmp.cleanup)
                _assert_invalid(self, validate_docx(str(template), str(document), profile))

    def test_empty_profile_is_rejected(self):
        tmp, template, document, _ = self._fixture()
        self.addCleanup(tmp.cleanup)
        _assert_invalid(self, validate_docx(str(template), str(document), {}))

    def test_duplicate_template_example_requires_explicit_occurrence(self):
        tmp, template, document, profile = self._fixture(duplicate_template=True)
        self.addCleanup(tmp.cleanup)
        _assert_invalid(self, validate_docx(str(template), str(document), profile))

        profile["bullet_sections"][0]["template_occurrence"] = 0
        _assert_valid(self, validate_docx(str(template), str(document), profile))

        profile["bullet_sections"][0]["template_occurrence"] = 2
        _assert_invalid(self, validate_docx(str(template), str(document), profile))

    def test_numbering_outside_rule_sections_does_not_create_false_positive(self):
        tmp, template, document, profile = self._fixture()
        self.addCleanup(tmp.cleanup)
        _assert_valid(self, validate_docx(str(template), str(document), profile))


if __name__ == "__main__":
    unittest.main()
