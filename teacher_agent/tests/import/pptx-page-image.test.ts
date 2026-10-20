import { describe, expect, it } from 'vitest';
import JSZip from 'jszip';
import sharp from 'sharp';
import { getPptxPageImage } from '@/lib/server/pptx-page-image';

async function imageDeck() {
  const zip = new JSZip();
  zip.file(
    'ppt/presentation.xml',
    `<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldIdLst><p:sldId r:id="second"/><p:sldId r:id="first"/></p:sldIdLst><p:sldSz cx="1600" cy="1200"/></p:presentation>`,
  );
  zip.file(
    'ppt/_rels/presentation.xml.rels',
    '<Relationships><Relationship Id="second" Target="slides/slide2.xml"/><Relationship Id="first" Target="slides/slide1.xml"/></Relationships>',
  );
  for (const [page, color] of [
    [1, '#ff0000'],
    [2, '#0000ff'],
  ] as const) {
    zip.file(
      `ppt/slides/slide${page}.xml`,
      '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:cSld><p:spTree><p:pic><p:blipFill><a:blip r:embed="image"/></p:blipFill><p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="1600" cy="1200"/></a:xfrm></p:spPr></p:pic></p:spTree></p:cSld></p:sld>',
    );
    zip.file(
      `ppt/slides/_rels/slide${page}.xml.rels`,
      `<Relationships><Relationship Id="image" Target="../media/image${page}.png"/></Relationships>`,
    );
    zip.file(
      `ppt/media/image${page}.png`,
      await sharp({ create: { width: 10, height: 10, channels: 3, background: color } })
        .png()
        .toBuffer(),
    );
  }
  return zip;
}
describe('PPTX OCR source image', () => {
  it('uses presentation order and embedded image relationships, without changing the original', async () => {
    const zip = await imageDeck();
    const image = await getPptxPageImage(zip, 1);
    const { data, info } = await sharp(image).raw().toBuffer({ resolveWithObject: true });
    expect(info).toMatchObject({ width: 1600, height: 1200 });
    expect(data[2]).toBeGreaterThan(240);
    expect(data[0]).toBeLessThan(10);
    await expect(getPptxPageImage(zip, 0)).rejects.toThrow('页码');
    await expect(getPptxPageImage(zip, 3)).rejects.toThrow('页码');
  });
  it('refuses external image relationships instead of fetching arbitrary URLs', async () => {
    const zip = await imageDeck();
    zip.file(
      'ppt/slides/_rels/slide2.xml.rels',
      '<Relationships><Relationship Id="image" Target="http://127.0.0.1/private" TargetMode="External"/></Relationships>',
    );
    await expect(getPptxPageImage(zip, 1)).rejects.toThrow('内嵌图片');
  });
});
