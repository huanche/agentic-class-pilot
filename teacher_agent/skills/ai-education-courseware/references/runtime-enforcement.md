# Runtime enforcement

## Platform boundaries

- Source fingerprinting: `lib/course-governance/fingerprint.ts`
- Governance rules and release gate: `lib/course-governance/governance.ts`
- Persistence: Dexie `courseGovernance` table in `lib/utils/database.ts`
- Import metadata: `lib/import/use-import-pptx.ts`
- Governance initialization and first-scene fallback: `app/generation-preview/page.tsx`
- Remaining-scene fallback: `lib/hooks/use-scene-generator.ts`
- Faithful narration brief and speech alignment: `lib/import/ppt-narration.ts`
- Versioned high-fidelity policy: `lib/import/high-fidelity-courseware-policy.ts`
- Content-aware playback viewport: `lib/import/content-aware-slide.ts`
- Narration-aware OpenMAIC action generation: `app/api/generate/scene-actions/route.ts`
- Per-page formula routing metadata: `lib/import/pptx-course.ts` and `lib/types/generation.ts`
- Semantic MathType conversion: `app/api/convert-mathtype-formula/route.ts`, `scripts/convert-mathtype-ole.py` and `packages/@openmaic/importer/src/serializer/mathSerializer.ts`
- Teacher review: `components/governance/course-release-review-dialog.tsx`
- Export enforcement: `lib/export/use-export-pptx.ts` and `lib/export/use-export-classroom.ts`

## Invariants to test

1. The same source bytes produce the same SHA-256; changing one byte changes it.
2. Faithful mode maps included source pages to scene order exactly.
3. Enhanced mode never creates a source-free scene.
4. New governance records initialize every scene as `pending`.
5. An approved scene passes only while its current fingerprint matches the reviewed fingerprint.
6. A rejected, pending, changed or missing scene blocks every governed export.
7. An unresolved blocker blocks release; a recorded fallback warning does not.
8. Generation/action/TTS failure creates a usable fallback scene and a degradation record.
9. Deleting a Stage cascades its governance record.
10. Courses without governance records preserve standard OpenMAIC export behavior.
11. Every included PPT page produces exactly one ordered narration brief; excluded pages produce none.
12. First-scene, remaining-scene and single-scene retry paths pass the matching narration brief by scene order.
13. Total spoken text per faithful scene stays within the configured narration ceiling while visual actions remain present.
14. Content/action fallback retains a speech action; TTS failure retains the existing speech and visual actions instead of replacing the scene with `actions: []`.
15. A page with one or more semantic LaTeX elements is marked `ai-formula-enhanced`; an ordinary page remains `faithful`.
16. Formula-enhanced scene orders bypass the imported canvas only during content generation; their fallback still receives the matching original source canvas.
17. Formula narration has its own ceiling, covers every extracted expression, and never sends raw LaTeX to TTS.
18. Long-formula narration explains terms and disciplinary meaning instead of spelling symbols or operators.
19. Every reviewed PPT draft persists the current high-fidelity policy version; behavior-changing releases bump it.
20. The teacher-approved review result, including deletion and reordering, defines final scene count and order.
21. Normal source canvases retain their viewport; only genuine visible bottom overflow expands the effective playback viewport.
22. Fully off-canvas animation assets and implausible element bounds never expand the playback viewport.
23. AI-enhanced conclusion elements remain hidden until their timeline `reveal` action; reveal is followed by semantically matching speech and is reconstructed after seeking.

## Stop conditions

Do not mark implementation complete when only `SKILL.md` or TypeScript types changed. At least one real PPTX must pass import, governance initialization, scene review, gate rejection before approval, gate success after approval, and a protected export.
