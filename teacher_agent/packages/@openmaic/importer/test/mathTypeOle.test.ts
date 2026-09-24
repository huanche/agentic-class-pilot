import { describe, expect, it } from 'vitest';
import { parseXml } from '../src/parser/XmlParser';
import { parseOleMathTypeNode } from '../src/model/nodes/MathNode';

describe('MathType OLE import', () => {
  it('recognizes Equation.DSMT4 and keeps both semantic and preview relationships', () => {
    const frame = parseXml(`
      <p:graphicFrame
        xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
        xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
        xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">
        <p:nvGraphicFramePr>
          <p:cNvPr id="8" name="Equation 7"/>
          <p:cNvGraphicFramePr/>
          <p:nvPr/>
        </p:nvGraphicFramePr>
        <p:xfrm><a:off x="914400" y="1828800"/><a:ext cx="2743200" cy="685800"/></p:xfrm>
        <a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/presentationml/2006/ole">
          <mc:AlternateContent>
            <mc:Choice Requires="v">
              <p:oleObj progId="Equation.DSMT4" r:id="rIdEquation">
                <p:pic><p:blipFill><a:blip r:embed="rIdPreview"/></p:blipFill></p:pic>
              </p:oleObj>
            </mc:Choice>
          </mc:AlternateContent>
        </a:graphicData></a:graphic>
      </p:graphicFrame>
    `);

    const node = parseOleMathTypeNode(frame);

    expect(node).toMatchObject({
      nodeType: 'math',
      oleMathTypeRId: 'rIdEquation',
      fallbackBlipEmbed: 'rIdPreview',
      position: { x: 96, y: 192 },
      size: { w: 288, h: 72 },
    });
  });

  it('does not claim unrelated embedded objects', () => {
    const frame = parseXml(`
      <p:graphicFrame xmlns:p="urn:p" xmlns:a="urn:a" xmlns:r="urn:r" xmlns:mc="urn:mc">
        <a:graphic><a:graphicData><mc:AlternateContent><mc:Choice>
          <p:oleObj progId="Excel.Sheet.12" r:id="rId1"/>
        </mc:Choice></mc:AlternateContent></a:graphicData></a:graphic>
      </p:graphicFrame>
    `);

    expect(parseOleMathTypeNode(frame)).toBeUndefined();
  });
});
