# Formula-page routing contract

Use this contract for PPTX pages containing native OMML, MathType or legacy Equation Editor formulas.

## Detection and conversion

- Detect formulas from semantic imported `latex` elements, not from text heuristics such as the presence of `=`.
- Prefer `OMML → MathML → LaTeX` or `MTEF → MathML → LaTeX`. Preserve the exact variables, subscripts, superscripts, bounds, coefficients and operators.
- Use KaTeX-backed OpenMAIC `latex` elements so formulas remain readable and editable. A calibrated source preview is fallback only.
- Persist `generationStrategy: ai-formula-enhanced` and the extracted formula list in the reviewed page draft. Record the generation policy version with the draft.

## Hybrid page routing

- Preserve reviewed page count, source identity and order.
- Ordinary pages use the imported source canvas.
- Formula pages call OpenMAIC scene-content generation so the model can allocate non-overlapping regions for title, explanation, formula and annotations.
- Pass every extracted LaTeX expression as an immutable constraint. The model may change layout but must not change formula semantics.
- Keep the matching original slide available to automatic fallback even though it is bypassed for normal formula-page generation.

## Spoken formula contract

- Cover the page's main visible conclusion and every extracted formula.
- Sequence: transition → problem or conclusion → formula purpose → key terms → overall relationship → page takeaway.
- A short formula may be spoken as a natural relationship. Never read LaTeX commands.
- For a long formula, do not spell every character or operator. Explain each important quantity, subscript, coefficient, integral/summation interval and their physical or disciplinary meaning.
- Ground symbol meanings in source text or notes. Do not guess an expansion when the source does not establish it.
- Target 260–420 Chinese characters; allow an absolute 520-character ceiling for multi-formula pages.
- Interleave at least one formula-targeted spotlight, highlight or laser action with the corresponding explanation. Only final natural-language speech actions go to TTS.

## Regression evidence

Test one ordinary page and one formula page in the same deck. Confirm route selection, exact LaTeX retention, non-overlapping generated layout, formula-aware speech, TTS audio, action adjacency and source-canvas fallback. Existing persisted classrooms do not migrate automatically; verify with a fresh import or explicit page regeneration.
