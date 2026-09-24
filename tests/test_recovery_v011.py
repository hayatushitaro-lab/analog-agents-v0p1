import importlib.util
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
def load(name):
    p=ROOT/'skills/analog-recovery-report/scripts'/name
    s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
f=load('fill_template.py');c=load('check_docx.py')

class FieldAndConditionTests(unittest.TestCase):
    def test_hidden_header_cannot_replace_footer(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'fake.docx'
            with ZipFile(p,'w',ZIP_DEFLATED) as z:
                z.writestr('word/header1.xml','<w:hdr xmlns:w="'+c.NS['w']+'"><w:p><w:fldSimple w:instr="NUMPAGES" w:fldLock="true"><w:r><w:rPr><w:vanish/></w:rPr><w:t>7</w:t></w:r></w:fldSimple></w:p></w:hdr>')
            self.assertNotIn(('footer','NUMPAGES',True),c.page_fields(p))
            self.assertNotIn(('header','NUMPAGES',True),c.page_fields(p))

    def test_real_template_has_usable_footer_field(self):
        self.assertIn(('footer','NUMPAGES',True),c.page_fields(f.PACKAGE/'template.docx'))

    def test_condition_factoring_keeps_differences(self):
        metric={'min':{'case_id':'a'},'typ':{'case_id':'a'},'max':{'case_id':'b'},'conditions':{'a':{'conditions':'TT，25C，load=1mA'},'b':{'conditions':'TT，25C，load=9mA'}}}
        text=f.compact_conditions(metric)
        self.assertEqual(1,text.count('25C'))
        self.assertIn('load=1mA',text);self.assertIn('load=9mA',text)
        self.assertNotIn('[a]',text)

    def test_template_build_preserves_fields(self):
        import json
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'good.docx';f.build(f.example_payload(),p)
            profile=json.loads((f.PACKAGE/'check-profile.json').read_text(encoding='utf-8'))
            self.assertTrue(c.validate(f.PACKAGE/'template.docx',p,profile)['valid'])
