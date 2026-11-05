import { test } from 'node:test';
import assert from 'node:assert/strict';
import JSZip from 'jszip';
import { DOMParser } from '@xmldom/xmldom';
import { compatiblePptx, normalizeLegacyHides } from './pptx-compat.mjs';
const ns = 'http://schemas.openxmlformats.org/presentationml/2006/main';
const group = (body) =>
  `<p:par><p:cTn nodeType="clickPar"><p:childTnLst><p:par><p:cTn nodeType="withGroup"><p:childTnLst>${body}</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par>`;
const hide = `<p:par><p:cTn id="10"><p:subTnLst><p:set><p:cBhvr><p:cTn masterRel="nextClick" afterEffect="1"/><p:tgtEl><p:spTgt spid="42"><p:txEl><p:pRg st="0" end="0"/></p:txEl></p:spTgt></p:tgtEl><p:attrNameLst><p:attrName>style.visibility</p:attrName></p:attrNameLst></p:cBhvr><p:to><p:strVal val="hidden"/></p:to></p:set></p:subTnLst></p:cTn></p:par>`;
const wrap = (groups) =>
  `<p:sld xmlns:p="${ns}"><p:timing><p:cTn nodeType="mainSeq"><p:childTnLst>${groups}</p:childTnLst></p:cTn></p:timing></p:sld>`;
test('next-click hiding stays in next existing click with paragraph target and unique IDs', () => {
  const result = normalizeLegacyHides(wrap(group(hide) + group('')));
  assert.equal(result.converted, 1);
  assert.equal(result.unresolved, 0);
  const doc = new DOMParser().parseFromString(result.xml, 'application/xml');
  const ctns = Array.from(doc.getElementsByTagNameNS(ns, 'cTn'));
  assert.equal(ctns.filter((n) => n.getAttribute('nodeType') === 'clickPar').length, 2);
  const exit = ctns.find((n) => n.getAttribute('presetClass') === 'exit');
  assert.ok(exit);
  assert.equal(exit.getElementsByTagNameNS(ns, 'spTgt')[0].getAttribute('spid'), '42');
  assert.equal(exit.getElementsByTagNameNS(ns, 'pRg')[0].getAttribute('end'), '0');
  assert.equal(
    Array.from(doc.getElementsByTagNameNS(ns, 'subTnLst')).some(
      (n) => n.getElementsByTagNameNS(ns, 'set').length,
    ),
    false,
  );
  const ids = ctns.map((n) => n.getAttribute('id')).filter(Boolean);
  assert.equal(new Set(ids).size, ids.length);
  assert.deepEqual(normalizeLegacyHides(result.xml), {
    xml: result.xml,
    converted: 0,
    unresolved: 0,
  });
});
test('last-click and unrelated behaviors are retained', () => {
  const xml = wrap(group(hide));
  assert.deepEqual(normalizeLegacyHides(xml), { xml, converted: 0, unresolved: 1 });
  const unrelated = xml.replace('nextClick', 'sameClick');
  assert.equal(normalizeLegacyHides(unrelated).xml, unrelated);
});
test('only affected slide XML changes in the package; source is not mutated', async () => {
  const zip = new JSZip();
  const xml = wrap(group(hide) + group(''));
  zip.file('ppt/slides/slide1.xml', xml);
  zip.file('ppt/slides/slide2.xml', '<p:sld xmlns:p="' + ns + '"/>');
  zip.file('ppt/media/image.png', Buffer.from([1, 2, 3]));
  const source = await zip.generateAsync({ type: 'nodebuffer' });
  const original = Buffer.from(source);
  const result = await compatiblePptx(source);
  assert.deepEqual(source, original);
  const output = await JSZip.loadAsync(result.bytes);
  assert.deepEqual(result.report.changed, ['ppt/slides/slide1.xml']);
  assert.deepEqual(
    await output.file('ppt/media/image.png').async('nodebuffer'),
    Buffer.from([1, 2, 3]),
  );
});
