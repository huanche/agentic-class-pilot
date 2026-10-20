import JSZip from 'jszip';
import { DOMParser } from '@xmldom/xmldom';
import { posix } from 'node:path';
import sharp from 'sharp';

const P = 'http://schemas.openxmlformats.org/presentationml/2006/main';
const A = 'http://schemas.openxmlformats.org/drawingml/2006/main';
const R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships';

function xmlDocument(xml: string) {
  if (xml.length > 2_000_000 || /<!DOCTYPE|<!ENTITY/i.test(xml)) {
    throw new Error('PPTX 页面结构不受支持');
  }
  return new DOMParser().parseFromString(xml, 'text/xml');
}

async function xmlFile(zip: JSZip, name: string) {
  const entry = zip.file(name);
  if (!entry) throw new Error('PPTX 页面文件不存在');
  return xmlDocument(await entry.async('text'));
}

async function relationships(zip: JSZip, source: string) {
  const name = posix.join(posix.dirname(source), '_rels', posix.basename(source) + '.rels');
  const doc = await xmlFile(zip, name);
  const result = new Map<string, string>();
  for (const item of Array.from(doc.getElementsByTagName('Relationship'))) {
    if (item.getAttribute('TargetMode') === 'External') continue;
    const target = item.getAttribute('Target') || '';
    const resolved = posix.normalize(
      target.startsWith('/') ? target.slice(1) : posix.join(posix.dirname(source), target),
    );
    if (resolved.startsWith('ppt/') && !resolved.includes('..')) {
      result.set(item.getAttribute('Id') || '', resolved);
    }
  }
  return result;
}

/** Follow presentation relationships: physical slide numbers need not match page order. */
export async function getPptxPageImage(zip: JSZip, page: number): Promise<Buffer> {
  const presentation = await xmlFile(zip, 'ppt/presentation.xml');
  const pages = Array.from(presentation.getElementsByTagNameNS(P, 'sldId'));
  if (!Number.isSafeInteger(page) || page < 1 || page > pages.length) {
    throw new Error('PPTX 页码超出范围');
  }
  const links = await relationships(zip, 'ppt/presentation.xml');
  const slideName = links.get(pages[page - 1].getAttributeNS(R, 'id') || '');
  if (!slideName) throw new Error('PPTX 页面关系不存在');
  const slide = await xmlFile(zip, slideName);
  const images = await relationships(zip, slideName);
  const size = presentation.getElementsByTagNameNS(P, 'sldSz')[0];
  const width = Number(size?.getAttribute('cx')) || 9144000;
  const height = Number(size?.getAttribute('cy')) || 6858000;
  const canvasWidth = 1600;
  const canvasHeight = Math.max(1, Math.round((height / width) * canvasWidth));
  if (canvasHeight > 6400) throw new Error('PPTX 页面比例不受支持');
  const layers: sharp.OverlayOptions[] = [];
  for (const picture of Array.from(slide.getElementsByTagNameNS(P, 'pic'))) {
    const blip = picture.getElementsByTagNameNS(A, 'blip')[0];
    const imagePath = images.get(blip?.getAttributeNS(R, 'embed') || '');
    const entry = imagePath && zip.file(imagePath);
    if (!entry) continue;
    const bytes = await entry.async('nodebuffer');
    if (bytes.length > 20 * 1024 * 1024) throw new Error('PPTX 图片过大');
    const transform = picture.getElementsByTagNameNS(A, 'xfrm')[0];
    const offset = transform?.getElementsByTagNameNS(A, 'off')[0];
    const extent = transform?.getElementsByTagNameNS(A, 'ext')[0];
    const left = Math.max(
      0,
      Math.round((Number(offset?.getAttribute('x')) / width || 0) * canvasWidth),
    );
    const top = Math.max(
      0,
      Math.round((Number(offset?.getAttribute('y')) / height || 0) * canvasHeight),
    );
    const w = Math.min(
      canvasWidth - left,
      Math.round((Number(extent?.getAttribute('cx')) / width || 1) * canvasWidth),
    );
    const h = Math.min(
      canvasHeight - top,
      Math.round((Number(extent?.getAttribute('cy')) / height || 1) * canvasHeight),
    );
    if (w <= 0 || h <= 0) continue;
    let image = sharp(bytes, { limitInputPixels: 40_000_000 });
    const crop = picture.getElementsByTagNameNS(A, 'srcRect')[0];
    if (crop) {
      const metadata = await image.metadata();
      const iw = metadata.width || 1;
      const ih = metadata.height || 1;
      const l = Math.round((Number(crop.getAttribute('l')) / 100000 || 0) * iw);
      const t = Math.round((Number(crop.getAttribute('t')) / 100000 || 0) * ih);
      const r = Math.round((Number(crop.getAttribute('r')) / 100000 || 0) * iw);
      const b = Math.round((Number(crop.getAttribute('b')) / 100000 || 0) * ih);
      if (l >= 0 && t >= 0 && iw - l - r > 0 && ih - t - b > 0) {
        image = image.extract({ left: l, top: t, width: iw - l - r, height: ih - t - b });
      }
    }
    layers.push({ input: await image.resize(w, h, { fit: 'fill' }).png().toBuffer(), left, top });
  }
  if (!layers.length) throw new Error('此页没有可识别的内嵌图片');
  return sharp({
    create: { width: canvasWidth, height: canvasHeight, channels: 3, background: '#ffffff' },
  })
    .composite(layers)
    .jpeg({ quality: 90 })
    .toBuffer();
}
