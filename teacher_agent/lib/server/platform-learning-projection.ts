/**
 * Projection helpers shared by the platform-facing read-only endpoints.
 *
 * They mirror the platform's legacy scene projection (student_bridge
 * ._classroom_view) so shadow comparisons stay meaningful: visible slide
 * text, ordered scenes and per-action speech lines. Media assets stay in
 * the player's own data channel and are never projected here.
 */

export type LooseRecord = Record<string, unknown>;

/** Mirror Python's html.unescape for the entities that occur in authored slides. */
const NAMED_ENTITIES: Record<string, string> = {
  amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ',
  copy: '©', reg: '®', trade: '™', hellip: '…',
  mdash: '—', ndash: '–', lsquo: '‘', rsquo: '’',
  ldquo: '“', rdquo: '”', laquo: '«', raquo: '»',
  times: '×', divide: '÷', plusmn: '±', deg: '°',
  middot: '·', bull: '•', dagger: '†', permil: '‰',
  larr: '←', uarr: '↑', rarr: '→', darr: '↓', harr: '↔',
  minus: '−', frac12: '½', frac14: '¼', frac34: '¾',
  sup2: '²', sup3: '³', micro: 'µ', para: '¶', sect: '§',
};

export function unescapeHtml(value: string): string {
  return value.replace(/&(#x?[0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]*);/g, (match, body: string) => {
    if (body.startsWith('#x') || body.startsWith('#X')) {
      const code = Number.parseInt(body.slice(2), 16);
      return Number.isFinite(code) ? String.fromCodePoint(code) : match;
    }
    if (body.startsWith('#')) {
      const code = Number.parseInt(body.slice(1), 10);
      return Number.isFinite(code) ? String.fromCodePoint(code) : match;
    }
    return NAMED_ENTITIES[body] ?? match;
  });
}

function visibleTextOf(scene: LooseRecord): string[] {
  const content = scene.content;
  const canvas = (content && typeof content === 'object' && !Array.isArray(content)
    ? (content as LooseRecord).canvas : undefined) as LooseRecord | undefined;
  const texts: string[] = [];
  for (const element of ((canvas?.elements as unknown[] | undefined) ?? [])) {
    if (element && typeof element === 'object' && !Array.isArray(element) &&
        (element as LooseRecord).type === 'text') {
      const raw = String((element as LooseRecord).content ?? '');
      const value = unescapeHtml(raw.replace(/<[^>]*>/g, ' ')).trim();
      if (value) texts.push(value);
    }
  }
  return texts;
}

export type ClassroomPayload = {
  id: string;
  stage?: unknown;
  scenes?: LooseRecord[];
};

/** Port of student_bridge._classroom_view (minus the platform-owned playerUrl). */
export function classroomView(classroom: ClassroomPayload): LooseRecord {
  const stage = classroom.stage;
  const title = stage && typeof stage === 'object' && !Array.isArray(stage)
    ? String((stage as LooseRecord).name ?? '')
    : '';
  const scenes = ((classroom.scenes ?? []) as LooseRecord[]).map((scene) => ({
    id: scene.id,
    type: (scene.type as string | undefined) ?? 'slide',
    order: Math.trunc(Number(scene.order) || 1),
    title: (scene.title as string | undefined) ?? '',
    visibleText: visibleTextOf(scene),
    actions: ((scene.actions ?? []) as unknown[])
      .filter((action): action is LooseRecord =>
        !!action && typeof action === 'object' && !Array.isArray(action))
      .map((action) => ({
        id: action.id,
        type: (action.type as string | undefined) ?? 'speech',
        text: action.text,
      })),
  }));
  scenes.sort((a, b) => a.order - b.order);
  return { id: classroom.id, title, scenes };
}
