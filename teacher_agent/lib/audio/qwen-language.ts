/** Resolve only known course languages; mixed-script input retains Qwen's Auto mode. */
export function qwenLanguageForText(text: string, preference: unknown): string {
  if (typeof preference !== 'string' || !preference.trim()) return 'Auto';
  const hint = preference.trim();
  const languages = [
    {
      name: 'Chinese',
      locale: 'zh',
      hint: /Chinese|中文|简体|繁体|普通话/i,
      scripts: /^[\p{Script=Han}]*$/u,
    },
    {
      name: 'Japanese',
      locale: 'ja',
      hint: /Japanese|日语|日本語/i,
      scripts: /^[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}]*$/u,
    },
    {
      name: 'Korean',
      locale: 'ko',
      hint: /Korean|韩语|한국어/i,
      scripts: /^[\p{Script=Han}\p{Script=Hangul}]*$/u,
    },
    {
      name: 'English',
      locale: 'en',
      hint: /English|英语|英文/i,
      scripts: /^[\p{Script=Latin}]*$/u,
    },
    { name: 'German', locale: 'de', hint: /German|德语/i, scripts: /^[\p{Script=Latin}]*$/u },
    { name: 'Italian', locale: 'it', hint: /Italian|意大利语/i, scripts: /^[\p{Script=Latin}]*$/u },
    {
      name: 'Portuguese',
      locale: 'pt',
      hint: /Portuguese|葡萄牙语/i,
      scripts: /^[\p{Script=Latin}]*$/u,
    },
    { name: 'Spanish', locale: 'es', hint: /Spanish|西班牙语/i, scripts: /^[\p{Script=Latin}]*$/u },
    { name: 'French', locale: 'fr', hint: /French|法语/i, scripts: /^[\p{Script=Latin}]*$/u },
    { name: 'Russian', locale: 'ru', hint: /Russian|俄语/i, scripts: /^[\p{Script=Cyrillic}]*$/u },
  ];
  if (/^auto$/i.test(hint)) return 'Auto';
  const language =
    languages.find((item) => new RegExp(`^${item.locale}(?:[-_]|$)`, 'i').test(hint)) ??
    languages.find((item) => item.hint.test(hint));
  // Punctuation, formulas and digits do not turn Chinese into a mixed-language sentence.
  const letters = text.normalize('NFKC').match(/\p{L}/gu)?.join('') ?? '';
  return language?.scripts.test(letters) ? language.name : 'Auto';
}
