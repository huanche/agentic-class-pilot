# High-fidelity generation contract

This contract fixes the verified teacher PPTX workflow as a versioned product behavior. The runtime source of truth is `lib/import/high-fidelity-courseware-policy.ts`; changing a routing, narration or canvas rule requires a policy-version bump and regression evidence.

## Stable pipeline

1. Hash and import the original PPTX bytes.
2. Extract every page's title, visible text, teacher notes, structured canvas and semantic formulas.
3. Let the teacher review, edit, remove and reorder pages. The approved review result—not the original file count—is the final page-count and ordering contract.
4. Route each reviewed page independently:
   - ordinary page: retain the imported source canvas and geometry;
   - semantic-formula page: retain identity, order, knowledge conclusion and exact LaTeX, then use OpenMAIC generation to rebuild a readable editable layout;
   - formula-generation failure: return to the original source canvas and record degradation.
5. Produce exactly one page-grounded narration brief per retained page. Formula pages use the formula spoken contract; long formulas are explained by term meaning, never by LaTeX spelling.
6. Generate speech interleaved with spotlight, highlight and laser actions. TTS consumes only final speech actions. TTS failure keeps text and visual actions.
7. During playback, keep normal pages geometrically unchanged. Expand only the effective viewport when an intended element crosses the source bottom edge; ignore fully off-canvas animation assets and implausible bounds.
8. Require current scene fingerprints, scene approvals and release-gate success before publication or download.

## Immutable acceptance criteria

- Policy version is persisted in the reviewed PPT draft.
- Final scene count and order equal the teacher-approved review result.
- Every retained page has one matching narration brief and no content from another page.
- Ordinary pages use the original visual canvas.
- Every extracted formula is preserved as semantic editable math on enhanced pages.
- Formula speech covers purpose, quantities, relationships and page conclusion without reading raw LaTeX.
- Automatic playback retains speech plus at least one appropriate visual action when available.
- A normal viewport is unchanged; genuine bottom overflow is visible without rewriting persisted element coordinates.
- Any failed governed step produces a usable fallback record and cannot silently bypass the release gate.

## Regression gate

Run the import contract, narration, content-aware viewport, governance and TypeScript checks for every change. Before a release candidate, run a real multi-page PPTX through upload, review (including page deletion/reordering), generation, autoplay, approval, publication and both downloads. Record the policy version, source SHA-256, reviewed page count, generated scene count, formula-page count, narration/TTS coverage and fallback count.
