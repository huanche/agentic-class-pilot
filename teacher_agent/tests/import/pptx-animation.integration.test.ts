// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import JSZip from 'jszip';
import PptxGenJS from 'pptxgenjs';
import { importPptx } from '@openmaic/importer';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { bindPptxAnimationsToActions } from '@/lib/import/pptx-animations';
import { validateScene } from '@openmaic/dsl';

/** Real PPTX ZIP, with the same nested timing structure emitted by PowerPoint. */
export async function animatedPptx(options: { unsupported?: boolean } = {}) {
  const ppt = new PptxGenJS();
  ppt.layout = 'LAYOUT_WIDE';
  const page = ppt.addSlide();
  page.addText('先讲原理', { x: 1, y: 1, w: 4, h: 1, fontSize: 28 });
  page.addText('再看例子', { x: 6, y: 1, w: 4, h: 1, fontSize: 28 });
  const bytes = (await ppt.write({ outputType: 'arraybuffer' })) as ArrayBuffer;
  const zip = await JSZip.loadAsync(bytes);
  let xml = await zip.file('ppt/slides/slide1.xml')!.async('string');
  const ids = [...xml.matchAll(/<p:cNvPr\s+id="(\d+)"/g)].map((match) => match[1]).slice(1);
  const effect = (
    id: number,
    target: string,
    kind: string,
    trigger: string,
    delay: number,
    exit = false,
  ) =>
    `<p:par><p:cTn id="${id}" presetID="${kind === 'fly' ? 2 : 10}" presetClass="${exit ? 'exit' : 'entr'}" presetSubtype="8" nodeType="${trigger}" fill="hold"><p:stCondLst><p:cond delay="${delay}"/></p:stCondLst><p:childTnLst><p:animEffect transition="${exit ? 'out' : 'in'}" filter="${kind}"><p:cBhvr><p:cTn id="${id + 1}" dur="600"/><p:tgtEl><p:spTgt spid="${target}"/></p:tgtEl></p:cBhvr></p:animEffect></p:childTnLst></p:cTn></p:par>`;
  const timing = `<p:timing><p:tnLst><p:par><p:cTn id="1" dur="indefinite" nodeType="tmRoot"><p:childTnLst><p:seq><p:cTn id="2" nodeType="mainSeq"><p:childTnLst><p:par><p:cTn id="3"><p:stCondLst><p:cond delay="indefinite"/></p:stCondLst><p:childTnLst>${effect(4, ids[0], 'fade', 'clickEffect', 0)}${effect(6, ids[1], 'fly', 'withEffect', 150)}${effect(8, ids[0], options.unsupported ? 'unsupported' : 'fade', 'clickEffect', 100, true)}</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:seq></p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>`;
  xml = xml.replace(
    '</p:sld>',
    `<p:transition spd="med"><p:fade/></p:transition>${timing}</p:sld>`,
  );
  zip.file('ppt/slides/slide1.xml', xml);
  return zip.generateAsync({ type: 'arraybuffer' });
}

describe('faithful PPTX source animations', () => {
  it('keeps the original targets, click groups, concurrent timing and exit effects', async () => {
    const [slide] = await importPptx(await animatedPptx());
    expect(slide).toHaveProperty('pptxAnimation.steps');
    const timeline = (
      slide as unknown as {
        pptxAnimation: {
          steps: Array<{
            effects: Array<{
              elementIds: string[];
              effect: string;
              phase: string;
              delayMs: number;
              durationMs: number;
            }>;
          }>;
        };
      }
    ).pptxAnimation;
    expect(timeline.steps).toHaveLength(3);
    expect(timeline.steps[0].effects[0]).toMatchObject({
      scope: 'slide',
      effect: 'fade',
      durationMs: 800,
    });
    expect(timeline.steps[1].effects).toHaveLength(2);
    expect(timeline.steps[1].effects[0]).toMatchObject({
      effect: 'fade',
      phase: 'in',
      delayMs: 0,
      durationMs: 600,
    });
    expect(timeline.steps[1].effects[1]).toMatchObject({
      effect: 'fly',
      phase: 'in',
      delayMs: 150,
    });
    expect(timeline.steps[2].effects[0]).toMatchObject({ phase: 'out', delayMs: 100 });
    const known = new Set(slide.elements.map((element) => element.id));
    known.add(slide.id);
    expect(
      timeline.steps
        .flatMap((step) => step.effects)
        .every((effect) => effect.elementIds.every((id) => known.has(id))),
    ).toBe(true);
    expect(timeline.steps[1].effects[0].elementIds).toEqual(
      timeline.steps[2].effects[0].elementIds,
    );
    expect(slide.turningMode).toBe('fade');
  });

  it('survives JSON persistence with schema-valid native playback actions', async () => {
    const [slide] = await importPptx(await animatedPptx());
    const actions = bindPptxAnimationsToActions(
      [
        { id: 'focus', type: 'spotlight', elementId: slide.elements[0].id },
        { id: 'speech', type: 'speech', text: '先讲原理。' },
      ],
      slide,
    );
    const scene = JSON.parse(
      JSON.stringify({
        id: 'scene',
        stageId: 'stage',
        type: 'slide',
        title: '动画测试',
        order: 1,
        content: { type: 'slide', canvas: slide },
        actions,
      }),
    );
    expect(validateScene(scene)).toMatchObject({ valid: true });
    expect(scene.actions.filter((action: { pptxStep?: unknown }) => action.pptxStep)).toHaveLength(
      3,
    );
  });

  it('keeps an object visible when any of its effects is unsupported', async () => {
    const [slide] = await importPptx(await animatedPptx({ unsupported: true }));
    const effects = slide.pptxAnimation!.steps.flatMap((step) => step.effects);
    expect(slide.pptxAnimation!.warnings).toHaveLength(1);
    expect(effects.filter((effect) => effect.scope !== 'slide')).toHaveLength(1);
    expect(effects.find((effect) => effect.scope !== 'slide')!.effect).toBe('fly');
  });

  it('retains paragraph targets and background-only builds independently', async () => {
    const zip = await JSZip.loadAsync(await animatedPptx());
    const source = await zip.file('ppt/slides/slide1.xml')!.async('string');
    let target = 0;
    zip.file(
      'ppt/slides/slide1.xml',
      source.replace(
        /<p:spTgt spid="(\d+)"\/>/g,
        (_, id) =>
          `<p:spTgt spid="${id}">${target++ === 0 ? '<p:txEl><p:pRg st="0" end="0"/></p:txEl>' : '<p:bg/>'}</p:spTgt>`,
      ),
    );
    const [slide] = await importPptx(await zip.generateAsync({ type: 'arraybuffer' }));
    const effects = slide
      .pptxAnimation!.steps.flatMap((step) => step.effects)
      .filter((effect) => effect.scope !== 'slide');
    expect(effects[0].paragraphRange).toEqual({ start: 0, end: 0 });
    expect(effects[1].backgroundOnly).toBe(true);
    expect(JSON.stringify(slide.elements)).toContain('data-pptx-paragraph');
  });

  it('starts an after-previous effect after the preceding effect has finished', async () => {
    const zip = await JSZip.loadAsync(await animatedPptx());
    const source = await zip.file('ppt/slides/slide1.xml')!.async('string');
    zip.file(
      'ppt/slides/slide1.xml',
      source.replace('nodeType="withEffect"', 'nodeType="afterEffect"'),
    );
    const [slide] = await importPptx(await zip.generateAsync({ type: 'arraybuffer' }));
    expect(slide.pptxAnimation!.steps[1].effects[1].delayMs).toBe(750);
  });

  it('preserves ordinary text carrying legacy Symbol font metadata', async () => {
    const zip = await JSZip.loadAsync(await animatedPptx());
    const source = await zip.file('ppt/slides/slide1.xml')!.async('string');
    zip.file(
      'ppt/slides/slide1.xml',
      source.replaceAll('</a:rPr>', '<a:sym typeface="Symbol"/></a:rPr>'),
    );
    const [slide] = await importPptx(await zip.generateAsync({ type: 'arraybuffer' }));
    expect(JSON.stringify(slide.elements)).toContain('先讲原理');
  });

  const originalSample = '.runtime/pptx-animation-20261025/Lec 6_1.animation-test.pptx';
  it.skipIf(!existsSync(originalSample))(
    'retains all 65 animation effects from the teacher original five-page test copy',
    async () => {
      const data = readFileSync(originalSample);
      const bytes = new Uint8Array(data.length);
      bytes.set(data);
      const slides = await importPptx(bytes.buffer);
      expect(slides).toHaveLength(5);
      const report = slides.map((slide, index) => ({
        page: index + 1,
        effects:
          slide.pptxAnimation?.steps
            .flatMap((step) => step.effects)
            .filter((effect) => effect.scope !== 'slide').length ?? 0,
        paragraphEffects:
          slide.pptxAnimation?.steps
            .flatMap((step) => step.effects)
            .filter((effect) => effect.paragraphRange).length ?? 0,
        warnings: slide.pptxAnimation?.warnings ?? [],
      }));
      writeFileSync(
        '.runtime/pptx-animation-20261025/import-report.json',
        JSON.stringify(report, null, 2),
      );
      writeFileSync('.runtime/pptx-animation-20261025/slides.json', JSON.stringify(slides));
      expect(report.map((page) => page.effects)).toEqual([13, 22, 14, 10, 6]);
      expect(report.reduce((sum, page) => sum + page.paragraphEffects, 0)).toBeGreaterThan(30);
    },
  );
});
