import sanitizeHtml from 'sanitize-html';

const escapeHtml = (value: string) =>
  value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');

function inlineMarkdown(value: string) {
  return escapeHtml(value)
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\[material:([^\]]+)\]/g, '<span class="source-citation">[material:$1]</span>')
    .replace(/\[p\.([^\]]+)\]/g, '<span class="source-citation">来源页 $1</span>');
}

export function markdownToArtifactHtml(markdown: string): string {
  const lines = markdown.replace(/\r\n/g, '\n').split('\n');
  const output: string[] = [];
  let list: 'ul' | 'ol' | null = null;
  const closeList = () => {
    if (list) output.push(`</${list}>`);
    list = null;
  };
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) {
      closeList();
      continue;
    }
    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    if (heading) {
      closeList();
      const level = heading[1].length;
      output.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }
    const unordered = /^[-*+]\s+(.+)$/.exec(line);
    const ordered = /^\d+[.)]\s+(.+)$/.exec(line);
    if (unordered || ordered) {
      const next = unordered ? 'ul' : 'ol';
      if (list !== next) {
        closeList();
        list = next;
        output.push(`<${next}>`);
      }
      output.push(`<li>${inlineMarkdown((unordered || ordered)![1])}</li>`);
      continue;
    }
    closeList();
    if (line.startsWith('> '))
      output.push(`<blockquote>${inlineMarkdown(line.slice(2))}</blockquote>`);
    else output.push(`<p>${inlineMarkdown(line)}</p>`);
  }
  closeList();
  return sanitizeHtml(output.join('\n'), {
    allowedTags: [
      'h1',
      'h2',
      'h3',
      'h4',
      'h5',
      'h6',
      'p',
      'ul',
      'ol',
      'li',
      'strong',
      'em',
      'code',
      'blockquote',
      'span',
    ],
    allowedAttributes: { span: ['class'] },
    allowedClasses: { span: ['source-citation'] },
  });
}

export const WORD_ARTIFACT_TYPES = new Set([
  'course-outline',
  'module-plan',
  'exercise-set',
  'assessment-rubric',
]);
