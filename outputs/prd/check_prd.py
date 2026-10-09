from pathlib import Path
from zipfile import ZipFile
from lxml import etree
from docx import Document
path=Path('outputs/prd/AI教育平台产品需求文档_PRD_v1.0.docx')
doc=Document(path)
ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
with ZipFile(path) as z:
    assert z.testzip() is None
    xml=etree.fromstring(z.read('word/document.xml'))
    text=''.join(xml.xpath('//w:t/text()',namespaces=ns))
    assert 'AI教育平台产品需求文档' in text
    assert '\ufffd' not in text
    assert len(xml.xpath('//w:br[@w:type="page"]',namespaces=ns))==8
    assert len(xml.xpath('//w:tbl',namespaces=ns))==8
    assert len(xml.xpath('//w:tblHeader',namespaces=ns))==8
    for table in doc.tables:
        assert all(len(row.cells)==len(table.columns) for row in table.rows)
        assert all(c.text.strip() for row in table.rows for c in row.cells)
    print('DOCX checks passed: valid package, 8 page breaks, 8 tables with repeating headers, Chinese content intact')
    print('characters',len(text),'bytes',path.stat().st_size)
