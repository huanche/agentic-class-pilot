export const courseMarkup = `
  <section class="view course-browser" id="view-courses" aria-labelledby="courses-title">
    <header class="course-browser__header">
      <span class="course-browser__brand"><img src="/app/brand-mark.png" alt="" class="course-browser__logo" />AI 学习空间 <span>· 学生端</span></span>
      <span class="course-browser__semester">2026—2027 学年 · 第一学期</span>
    </header>
    <div class="course-browser__intro">
      <p class="course-browser__eyebrow">我的课程</p>
      <h1 id="courses-title">选择一门课程</h1>
      <p>进入课程后，选择已经上过或本周正在学习的课时。</p>
    </div>
    <div class="course-grid" id="course-grid" aria-live="polite"></div>
  </section>

  <section class="view course-browser" id="view-weeks" hidden aria-labelledby="weeks-title">
    <header class="course-browser__header">
      <button class="back" data-back="courses" type="button">← 返回我的课程</button>
      <span class="course-browser__semester">2026—2027 学年 · 第一学期</span>
    </header>
    <div class="course-browser__intro">
      <p class="course-browser__eyebrow" id="weeks-course-name">课程</p>
      <h1 id="weeks-title">选择课时</h1>
      <p id="weeks-description">仅显示已上过和本周要上的课时。</p>
    </div>
    <div class="weeks-summary" id="weeks-summary"></div>
    <div class="week-grid" id="week-grid" aria-live="polite"></div>
  </section>
`;
