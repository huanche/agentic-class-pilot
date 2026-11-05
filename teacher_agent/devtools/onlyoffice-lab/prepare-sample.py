"""Extract original pages 5–9 without redrawing or rewriting their slide XML."""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET

P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
CT = 'http://schemas.openxmlformats.org/package/2006/content-types'
NS = {'p': P, 'a': A}
ET.register_namespace('p', P)
ET.register_namespace('a', A)
ET.register_namespace('r', R)

NARRATION = [
    [
        '内存地址，就是内存中存储单元的编号。先把地址理解成一个定位用的号码。',
        '看左边这座教学楼。每间教室有自己的号码，比如一零一、六零一。号码帮助我们找到教室。',
        '右边换成内存。这里的两千、两千零一，也是定位用的编号，并不是单元里保存的数据。',
        '把教学楼和内存对应起来，就容易区分位置、空间和内容了。',
        '教室号码对应存储地址。它回答的是在哪里，而不是里面有什么。',
        '教室对应存储单元。一个是实际的房间，一个是实际存放数据的空间。',
        '教室有容量，存储单元也有大小。讨论地址时，要分清定位信息和空间大小。',
        '现在看到单元里的五十。两千表示这个单元的地址，五十才是其中存放的数据。',
        '记住这条结论：内存单元的地址，与单元中保存的数据，是两个不同的概念。',
    ],
    [
        '接下来是变量的地址，也就是系统分配给这个变量的存储空间的起始地址。',
        '仍然看这张内存示意图。相邻的字节单元有不同的地址编号。',
        '每个字节都有编号。一个变量可以占用连续的多个字节，但变量地址通常指起始位置。',
        '程序声明了整型变量和浮点型变量。数据类型决定了怎样解释它们占用的存储空间。',
        '这一组箭头标出整型变量的位置。变量的名字与它的起始地址建立了联系。',
        '另一组箭头标出浮点型变量的位置。不同变量各自对应自己的存储空间。',
        '变量的存储空间会在相应的存储期内分配，具体方式与变量的声明和运行环境有关。',
        '所以，变量是程序对数据存储空间的一种抽象。变量名让程序不必处处直接写地址。',
        '原稿用不同编译环境说明整型大小可能不同。实际编程应使用大小运算符检查当前实现。',
    ],
    [
        '现在区分指针和指针变量，这两个术语有关联，但含义并不完全一样。',
        '这里把一个变量的地址称为指针。它标识的是变量在内存中的位置。',
        '指针变量则是一种专门保存地址的变量。它保存的内容，能够指向另一个变量。',
        '看图，整型变量里放的是十，旁边另有一个指针变量。先分清这两个存储位置。',
        '变量本身有地址。这个地址用来定位整型变量所在的单元。',
        '整型变量的内容是十。内容和地址不能混为一谈。',
        '图中标出的指针，表示整型变量所在的位置，也就是它的地址。',
        '把地址两千存入指针变量，就建立了从指针变量到整型变量的指向关系。',
        '此时指针变量的内容是地址两千，并不是目标变量中的数值十。',
        '因此，指针变量也是变量，只是它保存和使用的是地址信息。',
        '沿着箭头从指针变量出发，可以找到它所指向的目标变量。',
        '最后按图回顾：指针变量保存地址，地址指向目标变量，目标变量中保存具体数据。',
    ],
    [
        '这一页讨论取地址运算符和间接访问运算符，它们是指针操作的基础。',
        '理解它们时，始终区分变量的位置，和这个位置中保存的内容。',
        '取地址运算符作用于变量，得到这个变量的地址。它是单目运算符。',
        '星号用于间接访问时，根据指针找到目标对象，再访问目标对象的内容。',
        '在对象和指针都有效的前提下，取地址和间接访问可以形成互相对应的操作。',
        '不要只记符号。每一步都要问清楚，当前表达式得到的是地址，还是变量值。',
        '看右边的示意图。指针变量中保存两千，目标整型变量中保存十。',
        '这些表达式分成两组。一组取得地址，一组访问相应的目标变量。',
        '在图示条件下，可以按这两行对应关系，核对各表达式得到的结果。',
        '还要区分指针变量本身的地址。指针变量的地址，与它保存的目标地址，是两件事。',
        '用图再确认一次：目标位置是两千，目标内容是十，而指针变量自己也占有独立的存储位置。',
    ],
    [
        '最后看变量值的存取方法：可以直接访问，也可以通过指针间接访问。',
        '直接访问，就是通过变量名存取这个变量的值。',
        '间接访问，则通过保存地址的指针变量，找到目标变量后再进行存取。',
        '图中先建立指向关系。指针变量保存了整型变量的地址两千。',
        '执行变量赋值为三，是按变量名直接访问目标变量。',
        '观察图中的变化，目标变量原来的值被改成了三。存储位置并没有因此改变。',
        '接着通过星号和指针变量，把目标变量赋值为二十。这是间接访问。',
        '这组箭头表示访问路线：先从指针变量读出地址，再沿地址找到目标单元。',
        '最后目标变量变成二十。直接访问和间接访问使用的路线不同，但这里修改的是同一个变量。',
    ],
]
TITLES = ['内存地址与存储数据', '变量的地址', '指针与指针变量', '取地址与间接访问', '直接访问与间接访问']


def sha(data):
    return hashlib.sha256(data).hexdigest()


def rel_path(part):
    p = PurePosixPath(part)
    return str(p.parent / '_rels' / (p.name + '.rels'))


def target(source, value):
    result = posixpath.normpath(value.lstrip('/') if value.startswith('/') else posixpath.join(posixpath.dirname(source), value))
    if result.startswith('../'):
        raise ValueError('Invalid package relationship')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    original = args.source.read_bytes()
    args.output.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.source) as archive:
        files = {n: archive.read(n) for n in archive.namelist() if not n.endswith('/')}
    presentation = ET.fromstring(files['ppt/presentation.xml'])
    relationships = ET.fromstring(files['ppt/_rels/presentation.xml.rels'])
    slide_list = presentation.find(f'{{{P}}}sldIdLst')
    selected = list(slide_list)[4:9]
    if len(selected) != 5:
        raise ValueError('This test needs source pages 5 through 9')
    selected_rids = {s.get(f'{{{R}}}id') for s in selected}
    parts = [target('ppt/presentation.xml', next(r.get('Target') for r in relationships if r.get('Id') == s.get(f'{{{R}}}id'))) for s in selected]
    for s in list(slide_list):
        if s not in selected:
            slide_list.remove(s)
    for r in list(relationships):
        if r.get('Type', '').endswith('/slide') and r.get('Id') not in selected_rids:
            relationships.remove(r)
    # Sections/custom shows can contain old slide IDs; they are not part of the sample's visuals.
    for parent in presentation.iter():
        for child in list(parent):
            if child.tag.split('}')[-1] in {'sectionLst', 'custShowLst'}:
                parent.remove(child)
    files['ppt/presentation.xml'] = ET.tostring(presentation, encoding='utf-8', xml_declaration=True)
    files['ppt/_rels/presentation.xml.rels'] = ET.tostring(relationships, encoding='utf-8', xml_declaration=True)
    reachable = set()

    def visit(part):
        if part in reachable or part not in files:
            return
        reachable.add(part)
        rp = rel_path(part) if part else '_rels/.rels'
        if rp not in files:
            return
        reachable.add(rp)
        for relationship in ET.fromstring(files[rp]):
            if relationship.get('TargetMode') != 'External':
                visit(target(part, relationship.get('Target', '')))

    for relationship in ET.fromstring(files['_rels/.rels']):
        if relationship.get('TargetMode') != 'External':
            visit(target('', relationship.get('Target', '')))
    reachable.add('_rels/.rels')
    types = ET.fromstring(files['[Content_Types].xml'])
    for item in list(types):
        if item.tag == f'{{{CT}}}Override' and item.get('PartName', '').lstrip('/') not in reachable:
            types.remove(item)
    files['[Content_Types].xml'] = ET.tostring(types, encoding='utf-8', xml_declaration=True)
    reachable.add('[Content_Types].xml')
    dest = args.output / 'five-pages.pptx'
    with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(reachable):
            archive.writestr(name, files[name])
    pages = []
    for index, part in enumerate(parts):
        xml = ET.fromstring(files[part])
        shapes = {}
        for shape in xml.findall('.//p:sp', NS) + xml.findall('.//p:grpSp', NS):
            node = shape.find('.//p:cNvPr', NS)
            if node is not None:
                shapes[node.get('id')] = ' '.join((t.text or '') for t in shape.findall('.//a:t', NS)).strip()
        main_seq = next(t for t in xml.findall('.//p:cTn', NS) if t.get('nodeType') == 'mainSeq')
        groups = list(main_seq.find('p:childTnLst', NS))
        assert len(groups) == len(NARRATION[index]), 'Narration must align one-to-one to original click groups'
        cues = []
        for c, group in enumerate(groups):
            effects = [n for n in group.findall('.//p:cTn', NS) if n.get('presetClass')]
            last_start = last_end = 0
            effect_rows = []
            for effect in effects:
                duration = max([1] + [int(t.get('dur')) for t in effect.findall('.//p:cBhvr/p:cTn', NS) if (t.get('dur') or '').isdigit()])
                delay = sum(int(t.get('delay')) for t in effect.findall('./p:stCondLst/p:cond', NS) if (t.get('delay') or '').isdigit())
                start = (last_end if effect.get('nodeType') == 'afterEffect' else last_start if effect.get('nodeType') == 'withEffect' else 0) + delay
                last_start, last_end = start, start + duration
                ids = list(dict.fromkeys(t.get('spid') for t in effect.findall('.//p:spTgt', NS)))
                effect_rows.append({'id': effect.get('id'), 'class': effect.get('presetClass'), 'preset': effect.get('presetID'), 'targets': ids, 'text': ' / '.join(shapes.get(i, '') for i in ids)})
            cues.append({
                'click': c + 1, 'text': NARRATION[index][c],
                'audio': f'p{index+1}_c{c+1}.wav', 'durationMs': max(1, last_end),
                'effects': effect_rows,
                'effectSummary': ' / '.join(e['text'] or ('形状 ' + ','.join(e['targets'])) for e in effect_rows)[:150],
            })
        pages.append({
            'originalPage': index + 5, 'sourcePart': part, 'slideXmlSha256': sha(files[part]),
            'title': TITLES[index], 'cues': cues,
            'fonts': sorted({n.get('typeface') for n in xml.iter() if n.tag.split('}')[-1] in ['latin', 'ea', 'cs'] and n.get('typeface')}),
        })
    with zipfile.ZipFile(dest) as sample:
        for page in pages:
            assert sha(sample.read(page['sourcePart'])) == page['slideXmlSha256']
        assert len(ET.fromstring(sample.read('ppt/presentation.xml')).find(f'{{{P}}}sldIdLst')) == 5
    result = {'sourceSha256': sha(original), 'sampleSha256': sha(dest.read_bytes()), 'pages': pages}
    (args.output / 'sample.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'pages': len(pages), 'clickGroups': sum(len(p['cues']) for p in pages), 'sourceSha256': result['sourceSha256'], 'sampleSha256': result['sampleSha256'], 'slideXmlUnchanged': True, 'fonts': sorted({font for page in pages for font in page['fonts']})}, ensure_ascii=False))


if __name__ == '__main__':
    main()
