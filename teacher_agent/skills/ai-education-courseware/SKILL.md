---
name: ai-education-courseware
description: Convert teacher PPTX/PDF materials into governed OpenMAIC courseware when source traceability, high-fidelity or Learning Skills enhancement, scene-by-scene approval, automatic fallback, and release-gate enforcement are required. Do not use for ordinary topic-only OpenMAIC generation.
---

# AI Education Courseware

Create reviewable OpenMAIC courses from teacher-owned source materials. Treat governance as executable product behavior, not a report written after generation.

## Choose the conversion path

- Use `faithful` when page count, order and source canvas are authoritative. One included source page maps to one scene.
- Use `learning-skills-enhanced` when the teacher permits restructuring. Keep the source knowledge boundary and attach every generated scene to the strongest matching source pages.

Both paths must emit normal OpenMAIC Scene/Action data and use the shared classroom runtime.

## Mandatory controls

1. **Source version** — compute SHA-256 from the original file bytes before generation. Persist file metadata, page count and import time. Do not substitute a hash of extracted text or generated slides.
2. **Source traceability** — every scene must carry at least one source-page reference tied to the source SHA-256. Faithful scenes use the exact page; enhanced scenes use deterministic content matching and require teacher confirmation.
3. **Scene review** — initialize every scene as `pending`. Approval stores a fingerprint of the complete rendered scene and actions. Any later scene edit invalidates approval because the release gate recomputes the fingerprint.
4. **Automatic degradation** — generation, action or TTS failure must leave a usable scene. Prefer the original source canvas; otherwise create a readable source-backed text slide. Record the reason, fallback type, severity and resolution status.
5. **Release gate** — block PPTX, resource-pack, classroom-ZIP, HTML and video publication until the source fingerprint is valid, scene counts match, source references exist, every current scene fingerprint is approved, and no unresolved blocker remains.
6. **Faithful narration** — in faithful mode, build exactly one narration brief for every included source page and carry the ordered list through first-scene and remaining-scene generation. Generate concise spoken explanation from the page canvas, visible text, teacher notes and review comments; never merely read the slide or borrow content from another page. Preserve OpenMAIC-style interleaving of speech with spotlight, highlight and laser actions. TTS failure must not erase speech or visual actions, and content/action fallback must still contain page-grounded speech.
7. **Formula-page routing** — inspect each imported PPT page for semantic OMML/MathType formulas. Keep ordinary pages on the faithful source canvas, but route formula-bearing pages through OpenMAIC content generation using the exact extracted LaTeX as an immutable knowledge constraint. Preserve page identity and order. On generation failure, fall back to the original canvas.
8. **Formula narration** — formula pages use a dedicated spoken contract. Cover the page's main conclusion and every formula; explain purpose, key quantities and relationships. Never send LaTeX source or character-by-character operator reading to TTS. For a long formula, explain each term's physical or disciplinary meaning instead of reading the expression.
9. **Versioned high-fidelity contract** — persist the active generation-policy version in every reviewed PPT draft. A change to page routing, narration ceilings, formula behavior, source-canvas geometry or review ordering requires a policy-version bump and the complete regression gate. The teacher-approved review result is the authoritative page-count and ordering contract.
10. **Enhanced student-canvas hygiene and cue alignment** — Learning Skills governance notes remain teacher-only metadata and never appear on student slides. Generate visual cues as semantic pairs: spotlight/laser the relevant existing element immediately before speech that explains the same visible knowledge point. If no reliable target exists, keep the speech and omit the misleading cue.
11. **Automatic conclusion reveal** — on suitable Learning Skills enhanced slides, generate the conclusion or key takeaway as an independent element. Keep it hidden while evidence and body content are explained, then execute one timeline `reveal` action followed immediately by matching conclusion speech. Reveal must be automatic, reconstruct correctly after playback seeking, and never require a teacher click.

Never bypass a failed gate by exporting through another format. Ordinary topic-only courses without a governance record remain outside this workflow.

## Workflow

1. Import and fingerprint the original file.
2. Extract page title, text, notes and structured canvas data.
3. Let the teacher select the conversion path and review extracted source content.
4. Create the Stage and persist its governance record before generating the first scene.
5. Generate scenes and actions; apply and record fallback immediately when a governed step fails.
6. Present source references and degradation records in the scene review UI.
7. Require explicit approval for every final scene.
8. Re-evaluate the release gate at export time, not only when the export menu is rendered.

Read [references/course-package-contract.md](references/course-package-contract.md) when changing persisted types or export manifests. Read [references/runtime-enforcement.md](references/runtime-enforcement.md) when implementing or reviewing platform integration and tests.
Read [references/faithful-narration-quality.md](references/faithful-narration-quality.md) whenever changing PPT/PDF narration, action generation, TTS, autoplay or fallback behavior.
Read [references/formula-page-routing.md](references/formula-page-routing.md) whenever changing formula extraction, formula-page generation, layout, spoken explanation or formula fallback.
Read [references/high-fidelity-generation-contract.md](references/high-fidelity-generation-contract.md) for every change to the high-fidelity PPTX workflow, its policy version or its release regression gate.

## Required validation output

Report the source SHA-256, conversion mode, source page and scene counts, approved scene count, fallback records, unresolved blockers, release-gate result, tested export formats and remaining risks. Never describe a course as publishable when the runtime gate has not returned `ready: true`.
