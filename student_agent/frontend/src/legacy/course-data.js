/* 演示目录。真实接入时由后端按学生选课、发布和授课进度返回。 */
export const DEMO_TERM_START = "2026-09-01";

const definitions = [
  {
    courseId: "advanced-math", name: "高等数学", icon: "∫",
    summary: "从极限与导数出发，逐步理解微积分的思想与应用。",
    topics: ["函数与极限", "极限的运算法则", "连续与间断", "导数的概念", "求导法则", "微分及其应用", "中值定理", "函数的单调性", "不定积分", "定积分", "积分的应用", "微分方程初步", "多元函数", "偏导数", "重积分", "课程总结"]
  },
  {
    courseId: "linear-algebra", name: "线性代数", icon: "▦",
    summary: "用矩阵和向量描述线性关系，建立抽象与计算之间的联系。",
    topics: ["行列式", "矩阵及其运算", "逆矩阵", "矩阵的初等变换", "矩阵的秩", "线性方程组", "向量组的线性相关性", "向量空间", "特征值与特征向量", "相似矩阵", "对角化", "二次型", "正定矩阵", "正交变换", "综合应用", "课程总结"]
  },
  {
    courseId: "communication-principles", name: "通信原理", icon: "◉",
    summary: "理解信号、信道与调制，认识信息可靠传输的基本方法。",
    topics: ["通信系统概述", "信号与频谱", "信道与噪声", "模拟调制", "角度调制", "模拟信号数字化", "数字基带传输", "数字频带传输", "最佳接收", "同步原理", "差错控制编码", "信息论基础", "多址技术", "无线信道", "系统设计实例", "课程总结"]
  },
  {
    courseId: "operating-systems", name: "操作系统", icon: "⌘",
    summary: "从进程与资源管理出发，理解计算机如何协调多个任务。",
    topics: ["操作系统概述", "进程与线程", "处理机调度", "进程同步", "死锁", "内存管理", "虚拟内存", "文件系统", "设备管理", "磁盘调度", "系统安全", "Linux 基础", "并发程序设计", "性能分析", "综合实践", "课程总结"]
  }
];

export function currentDemoWeek(now = new Date()) {
  const start = new Date(DEMO_TERM_START + "T00:00:00+08:00").getTime();
  return Math.max(0, Math.min(16, Math.floor((now.getTime() - start) / (7 * 86400000)) + 1));
}

export function buildMockCourses(now = new Date()) {
  const currentWeek = currentDemoWeek(now);
  return definitions.map((definition) => ({
    ...definition,
    currentWeek,
    lessons: definition.topics.map((title, index) => {
      const week = index + 1;
      return {
        lessonId: definition.courseId === "operating-systems" && week === 3
          ? "ch3-process-scheduling" : `${definition.courseId}-week-${week}`,
        week,
        chapter: `第 ${week} 周`,
        title,
        summary: `本周学习${title}，通过课堂互动梳理概念与应用。`,
        status: week < currentWeek ? "completed" : week === currentWeek ? "current" : "upcoming",
        estimatedMinutes: 45,
        knowledgePoints: [title, `${title}的核心概念`, `${title}的典型应用`]
      };
    })
  }));
}

export function findMockLesson(lessonId) {
  for (const course of buildMockCourses()) {
    const lesson = course.lessons.find((item) => item.lessonId === lessonId);
    if (lesson) return { course, lesson };
  }
  return null;
}
