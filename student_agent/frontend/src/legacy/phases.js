/* ═══════════════════════════════════════════════════════════
   阶段词表 —— 后端 host_phase 与前端界面之间的唯一映射

   取值来源：ORCHESTRATOR.md §2 的
     host_phase: Literal["uninitialized", "intro", "guided_learning",
                         "recap_discussion", "deep_inquiry",
                         "class_discussion", "ending"]

   前端不决定演到哪一幕，只负责把后端说的那一幕显示出来。
   ═══════════════════════════════════════════════════════════ */

/* host_phase → 该显示哪个界面（app.js 的 stage 名）

   注意 guided_learning：它内部还有「AI 对话」和「教学视频」两段，
   后者是前端自己的局部状态，不由 host_phase 区分。 */
export var UI_OF_PHASE = {
  uninitialized:    "idle",
  intro:            "chat",
  guided_learning:  "chat",
  /* Compatibility for sessions created before the platform adapter aligned
     its stage id with the public frontend contract. */
  teach:             "chat",
  recap_discussion: "summary",
  deep_inquiry:     "reflect",
  class_discussion: "discuss",
  ending:           "done"
};

/* 页头上显示的状态名。这是学生判断「现在在哪一步」的唯一依据 */
export var LABEL_OF_PHASE = {
  uninitialized:    "课前",
  intro:            "课程介绍",
  guided_learning:  "引导学习",
  teach:             "引导学习",
  recap_discussion: "总结复述",
  deep_inquiry:     "深入思考",
  class_discussion: "课堂讨论",
  ending:           "已结束"
};

export function uiOf(phase) {
  return UI_OF_PHASE[phase] || null;
}

export function labelOf(phase) {
  return LABEL_OF_PHASE[phase] || "";
}

/* 后端给了一个前端不认识的 phase 时，不崩、不切界面，只在控制台留痕。
   前端升到新版本前，后端加新阶段不会把课堂打断。 */
export function isKnown(phase) {
  return Object.prototype.hasOwnProperty.call(UI_OF_PHASE, phase);
}
