import JSZip from 'jszip';
import { DOMParser, XMLSerializer } from '@xmldom/xmldom';
import path from 'node:path';

const P = 'http://schemas.openxmlformats.org/presentationml/2006/main';
const nodes = (root, name) => Array.from(root.getElementsByTagNameNS(P, name));
const direct = (root, name) =>
  Array.from(root.childNodes).find((n) => n.namespaceURI === P && n.localName === name);
const element = (doc, name, attrs = {}) => {
  const n = doc.createElementNS(P, 'p:' + name);
  for (const [key, value] of Object.entries(attrs)) n.setAttribute(key, String(value));
  return n;
};

/** Convert legacy next-click hide to an explicit exit in the NEXT existing click.
 * No visual shapes, text, page order, or extra click groups are introduced.
 */
export function normalizeLegacyHides(xml) {
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  const main = nodes(doc, 'cTn').find((n) => n.getAttribute('nodeType') === 'mainSeq');
  if (!main) return { xml, converted: 0, unresolved: 0 };
  const list = direct(main, 'childTnLst');
  const groups = list ? Array.from(list.childNodes).filter((n) => n.nodeType === 1) : [];
  let id = Math.max(0, ...nodes(doc, 'cTn').map((n) => Number(n.getAttribute('id')) || 0)) + 1;
  let converted = 0,
    unresolved = 0;
  for (let i = 0; i < groups.length; i++) {
    for (const set of [...nodes(groups[i], 'set')]) {
      if (set.parentNode?.localName !== 'subTnLst') continue;
      const behavior = direct(set, 'cBhvr');
      const timing = behavior && direct(behavior, 'cTn');
      if (
        timing?.getAttribute('masterRel') !== 'nextClick' ||
        timing.getAttribute('afterEffect') !== '1'
      )
        continue;
      if (
        !nodes(set, 'attrName').some((n) => n.textContent === 'style.visibility') ||
        !nodes(set, 'strVal').some((n) => n.getAttribute('val') === 'hidden')
      )
        continue;
      const target = direct(behavior, 'tgtEl');
      const next = groups[i + 1];
      // A hide after the last click is left intact; page navigation removes it.
      if (!next || !target) {
        unresolved++;
        continue;
      }
      const container = nodes(next, 'cTn').find((n) => n.getAttribute('nodeType') === 'withGroup');
      const destination = container && direct(container, 'childTnLst');
      if (!destination) {
        unresolved++;
        continue;
      }
      const par = element(doc, 'par');
      const effect = element(doc, 'cTn', {
        id: id++,
        presetID: 1,
        presetClass: 'exit',
        presetSubtype: 0,
        nodeType: 'withEffect',
        fill: 'hold',
      });
      const start = element(doc, 'stCondLst');
      start.appendChild(element(doc, 'cond', { delay: 0 }));
      effect.appendChild(start);
      const children = element(doc, 'childTnLst');
      const hide = element(doc, 'set');
      const bhvr = element(doc, 'cBhvr');
      bhvr.appendChild(element(doc, 'cTn', { id: id++, dur: 1, fill: 'hold' }));
      bhvr.appendChild(target.cloneNode(true));
      const attrs = element(doc, 'attrNameLst');
      const attr = element(doc, 'attrName');
      attr.appendChild(doc.createTextNode('style.visibility'));
      attrs.appendChild(attr);
      bhvr.appendChild(attrs);
      hide.appendChild(bhvr);
      const to = element(doc, 'to');
      to.appendChild(element(doc, 'strVal', { val: 'hidden' }));
      hide.appendChild(to);
      children.appendChild(hide);
      effect.appendChild(children);
      par.appendChild(effect);
      destination.insertBefore(par, destination.firstChild);
      set.parentNode.removeChild(set);
      converted++;
    }
  }
  return {
    xml: converted ? new XMLSerializer().serializeToString(doc) : xml,
    converted,
    unresolved,
  };
}

export async function compatiblePptx(bytes) {
  const zip = await JSZip.loadAsync(bytes, { checkCRC32: true });
  const files = Object.keys(zip.files);
  if (files.length > 12000) throw new Error('PPTX 包含过多文件');
  let converted = 0,
    unresolved = 0;
  const changed = [];
  const presentation = zip.file('ppt/presentation.xml');
  const pageCount = presentation
    ? nodes(
        new DOMParser().parseFromString(await presentation.async('string'), 'application/xml'),
        'sldId',
      ).length
    : 0;
  for (const name of files.filter((n) => /^ppt\/slides\/slide\d+\.xml$/.test(n))) {
    const original = await zip.file(name).async('string');
    if (original.length > 15_000_000) throw new Error('PPTX 页面过大');
    const result = normalizeLegacyHides(original);
    converted += result.converted;
    unresolved += result.unresolved;
    if (result.converted) {
      zip.file(name, result.xml);
      changed.push(name);
    }
  }
  return {
    bytes: converted
      ? await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' })
      : Buffer.from(bytes),
    report: { version: 1, converted, unresolved, changed, pageCount },
  };
}

/** Read every original click, including effects the web importer cannot model.
 * Effect node identities also map supported legacy actions back to their click.
 */
export async function nativeClickManifest(bytes) {
  const zip = await JSZip.loadAsync(bytes);
  const parse = async (name) =>
    new DOMParser().parseFromString(await zip.file(name).async('string'), 'application/xml');
  const presentation = await parse('ppt/presentation.xml');
  const rels = await parse('ppt/_rels/presentation.xml.rels');
  const relation = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships';
  const relationships = Array.from(rels.documentElement.childNodes).filter((n) => n.nodeType === 1);
  const pages = [];
  for (const entry of nodes(presentation, 'sldId')) {
    const rid = entry.getAttributeNS(relation, 'id');
    const rel = relationships.find((n) => n.getAttribute('Id') === rid);
    const target = rel?.getAttribute('Target');
    if (!target) throw new Error('原稿页面关系缺失');
    const name = target.startsWith('/') ? target.slice(1) : path.posix.normalize('ppt/' + target);
    if (!/^ppt\/slides\/[^/]+\.xml$/.test(name)) throw new Error('原稿页面关系无效');
    const doc = await parse(name);
    const texts = new Map();
    for (const shape of [...nodes(doc, 'sp'), ...nodes(doc, 'grpSp'), ...nodes(doc, 'pic')]) {
      const identity = nodes(shape, 'cNvPr')[0]?.getAttribute('id');
      if (!identity) continue;
      texts.set(
        identity,
        Array.from(
          shape.getElementsByTagNameNS(
            'http://schemas.openxmlformats.org/drawingml/2006/main',
            't',
          ),
        )
          .map((n) => n.textContent)
          .join(' ')
          .trim(),
      );
    }
    const main = nodes(doc, 'cTn').find((n) => n.getAttribute('nodeType') === 'mainSeq');
    const groupList = main && direct(main, 'childTnLst');
    const groups = groupList
      ? Array.from(groupList.childNodes).filter((n) => n.nodeType === 1)
      : [];
    const clicks = groups.map((group, index) => {
      const effects = nodes(group, 'cTn').filter((n) => n.hasAttribute('presetClass'));
      let lastStart = 0,
        lastEnd = 0,
        end = 1;
      const descriptions = [];
      for (const effect of effects) {
        const durations = nodes(effect, 'cBhvr').flatMap((b) => [
          Number(direct(b, 'cTn')?.getAttribute('dur')) || 1,
        ]);
        const duration = Math.max(1, ...durations);
        const condition = direct(effect, 'stCondLst');
        const delay = condition
          ? nodes(condition, 'cond').reduce(
              (sum, n) => sum + (Number(n.getAttribute('delay')) || 0),
              0,
            )
          : 0;
        const type = effect.getAttribute('nodeType');
        const start =
          (type === 'afterEffect' ? lastEnd : type === 'withEffect' ? lastStart : 0) + delay;
        lastStart = start;
        lastEnd = start + duration;
        end = Math.max(end, lastEnd);
        const ids = [...new Set(nodes(effect, 'spTgt').map((n) => n.getAttribute('spid')))];
        const label = ids.map((id) => texts.get(id) || `图形 ${id}`).join('；');
        descriptions.push(
          `${effect.getAttribute('presetClass') === 'exit' ? '移出' : '显示'}：${label}`.slice(
            0,
            800,
          ),
        );
      }
      if (!Number.isFinite(end) || end > 300000) throw new Error('原稿动画组时长超出支持范围');
      return {
        id: `onlyoffice-click-${index + 1}`,
        durationMs: end,
        sourceEffectIds: effects.map((n) => n.getAttribute('id')).filter(Boolean),
        description: descriptions.join('；').slice(0, 1800),
      };
    });
    const transition = nodes(doc, 'transition')[0];
    const explicit =
      Number(
        transition?.getAttributeNS(
          'http://schemas.microsoft.com/office/powerpoint/2010/main',
          'dur',
        ),
      ) || 0;
    pages.push({
      clicks,
      transitionMs: Math.min(300000, Math.max(explicit, transition ? 1400 : 0)),
    });
  }
  return pages;
}
