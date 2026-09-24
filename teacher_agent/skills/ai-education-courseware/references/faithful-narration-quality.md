# Faithful narration quality contract

Use this contract for high-fidelity PPTX/PDF courseware. Page count, included-page order and original visual canvas remain authoritative.

## Per-page inputs

Build one ordered narration brief from each included page:

- page title and visible text;
- original speaker notes;
- teacher review comments;
- the matching scene outline and key points;
- previous-page speech only as transition context.

Never use text from a different source page as factual content. The narration-brief array and imported-slide array must use the same included-page order.

## Spoken explanation

Follow the OpenMAIC slide-action pattern: speech explains while spotlight, highlight and laser actions direct attention to the relevant visual elements.

- Do not read the title and bullets verbatim.
- Explain one core logic through “why”, “how to understand” or “how to apply”.
- Use at most one useful example, analogy or observation cue.
- Use one short transition when it adds continuity; do not recap the entire previous page.
- For ordinary faithful pages, target 140–200 Chinese characters and enforce an absolute ceiling of 220 characters after generation.
- Formula-routed pages are the deliberate exception: target 260–420 Chinese characters and allow up to 500–520 characters when multiple formulas or substantial page conclusions require it. Do not truncate before every formula and the main page conclusion have been explained.
- Keep terminology and claims grounded in the current page. Do not invent numerical values, conclusions or examples that contradict the source.

The final speech actions—not the prompt brief—are the only text sent to TTS. When several speech actions surround visual actions, distribute the final narration across those slots without changing the visual-action order.

## Failure behavior

- Content or action generation failure: retain the original PPT canvas and create a source-grounded speech action, then attempt TTS.
- TTS failure: retain all speech and visual actions, record audio degradation, and allow later audio retry. Never replace the scene with an empty-action fallback.
- A page with no original notes still receives a concise explanation derived from its title, visible content and reviewed outline.

## Required regression checks

Verify an included/excluded page fixture, multi-page ordered mapping, narration ceiling, preservation of visual actions, fallback speech, and TTS-failure retention. For a release candidate, run one real multi-page PPTX through upload, review, generation and autoplay; confirm every page has visible lecture notes and audible narration where TTS succeeds.

For formula pages, also verify that final speech contains no LaTeX commands, covers every extracted formula, explains long expressions term-by-term, and keeps at least one adjacent spotlight/highlight/laser action aimed at the formula.
