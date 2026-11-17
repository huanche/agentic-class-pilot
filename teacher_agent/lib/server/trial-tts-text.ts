import { spawn } from 'node:child_process';
import path from 'node:path';

const cTypes: Record<string, string> = {
  int: '整型',
  short: 'short 类型',
  'short int': 'short 类型',
};

export function verbalizeTrialSpeech(text: string): string {
  if (!/\p{Script=Han}/u.test(text)) return text;
  const units = /sizeof|字节|内存|数组/.test(text);
  const spoken = text
    .replace(
      /\b(short\s+int|int|short)\s+([A-Za-z])\s*\[\s*(\d+)\s*\](?!\s*[\[=])/g,
      (_, type: string, name: string, count: string) =>
        '包含' +
        count +
        '个' +
        cTypes[type.replace(/\s+/g, ' ')] +
        '元素的数组 ' +
        name.toUpperCase(),
    )
    .replace(/\bsizeof\s*\(\s*short\s*\)\s*等于\s*(\d+)\s*B\b/g, '一个 short 类型的整数占$1个字节')
    .replace(
      /执行\s*return\s+([A-Za-z])\s*\[\s*([A-Za-z]|\d+)\s*\][，,]\s*就返回\s*\1\s*\[\s*\2\s*\]/g,
      '执行这条 return 语句，就返回数组 $1 中下标为 $2 的元素',
    )
    .replace(
      /\breturn\s+([A-Za-z])\s*\[\s*([A-Za-z]|\d+)\s*\](?=\s*(?:[，。；,;]|$))/g,
      (_, name: string, index: string) =>
        'return，返回数组 ' + name.toUpperCase() + ' 中下标为 ' + index.toUpperCase() + ' 的元素',
    )
    .replace(/\b([A-Za-z])\s*\*\s*([A-Za-z])\s*(?:是|表示)乘法/g, '$1 和 $2 之间的星号表示相乘')
    .replace(
      /(?<![A-Za-z0-9_])\*\s*([A-Za-z])\s*(?:是|表示)取(?:出)?指针\s*\1\s*指向的值/g,
      '写在指针 $1 前面的星号，表示取出它指向的值',
    );
  return units ? spoken.replace(/\b(\d+(?:\.\d+)?)\s*B\b/g, '$1个字节') : spoken;
}

export async function prepareTrialNarration(
  texts: string[],
  signal?: AbortSignal,
): Promise<string[]> {
  signal?.throwIfAborted();
  const spoken = texts.map(verbalizeTrialSpeech);
  const python = process.env.COURSEWARE_TRIAL_TN_PYTHON;
  if (!python || !spoken.some((text) => /\p{Script=Han}/u.test(text))) return spoken;

  return new Promise((resolve, reject) => {
    const child = spawn(python, [path.join(process.cwd(), 'scripts', 'normalize-trial-tts.py')], {
      signal: signal
        ? AbortSignal.any([signal, AbortSignal.timeout(4000)])
        : AbortSignal.timeout(4000),
      stdio: ['pipe', 'pipe', 'ignore'],
      windowsHide: true,
    });
    let output = '';
    child.stdout.setEncoding('utf8').on('data', (chunk: string) => {
      output += chunk;
    });
    child.stdin.on('error', () => {});
    child.on('error', () => {
      if (signal?.aborted) reject(signal.reason);
      else resolve(spoken);
    });
    child.on('close', (code) => {
      if (signal?.aborted) return reject(signal.reason);
      if (code !== 0) return resolve(spoken);
      try {
        const normalized: unknown = JSON.parse(output);
        resolve(
          Array.isArray(normalized) && normalized.length === spoken.length
            ? spoken.map((text, index) =>
                typeof normalized[index] === 'string' && normalized[index].trim()
                  ? normalized[index]
                  : text,
              )
            : spoken,
        );
      } catch {
        resolve(spoken);
      }
    });
    child.stdin.end(JSON.stringify(spoken), 'utf8');
  });
}
