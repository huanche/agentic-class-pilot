import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  CourseDurationInput,
  courseDurationInputError,
} from '@/components/generation/course-duration-input';
import { CourseDurationSummary } from '@/components/generation/course-duration-summary';
import {
  planCourseDuration,
  resolveCourseMinutes,
  withSceneContentDuration,
} from '@/lib/generation/course-duration';
import { formatPlaybackDuration } from '@/lib/playback/timing-display';
import type { SceneOutline } from '@/lib/types/generation';
import type { Scene, Stage } from '@/lib/types/stage';

interface Fixture {
  name: string;
  scenes: Scene[];
  audioSeconds: number;
  audioClips: number;
}

function Preview() {
  const [value, setValue] = useState('');
  const [fixtures, setFixtures] = useState<Fixture[]>([]);
  const [selected, setSelected] = useState(0);
  useEffect(() => {
    fetch('/fixtures')
      .then((response) => response.json())
      .then(setFixtures);
  }, []);
  const error = courseDurationInputError(value);
  const minutes = error ? 28 : resolveCourseMinutes(value);
  const fixture = fixtures[selected];
  const originalOutlines: SceneOutline[] = fixture
    ? fixture.scenes.map((scene, index) => ({
        id: scene.id,
        type: scene.type,
        title: scene.title,
        description: '',
        keyPoints: [],
        order: index + 1,
        estimatedDuration: 60,
      }))
    : Array.from({ length: 10 }, (_, index) => ({
        id: String(index + 1),
        type: 'slide',
        title: `示例页 ${index + 1}`,
        description: '',
        keyPoints: [],
        order: index + 1,
        estimatedDuration: 60,
      }));
  const outlines = planCourseDuration(originalOutlines, minutes);
  const automatic = outlines.filter((outline) => outline.durationBudget);
  const stage = {
    timing: {
      budgetVersion: 1,
      targetDurationMinutes: minutes,
      expectedAutomaticPages: automatic.length,
    },
  } as Stage;
  return (
    <main>
      <h1>课件时长 · 本地离线测试</h1>
      <p>
        此页使用工程中的真实输入组件、预算规则和音频测量代码。未调用大模型或
        TTS，不代表新生成课件已达到目标时长。
      </p>
      <section>
        <CourseDurationInput value={value} onChange={setValue} />
        <div className="buttons">
          <button onClick={() => setValue('')}>留空：默认 28 分钟</button>
          <button onClick={() => setValue('20')}>试试 20 分钟</button>
        </div>
      </section>
      <section>
        <h2>时长如何影响内容</h2>
        <p>
          教师目标 → 大纲规划知识点、案例与页数 → 页面生成可见的例题、步骤和演示 →
          生成正常语速的讲解 → 配音实测校验。
        </p>
        <p>
          时间预算用于指导内容生成。它不会让旧 JSON
          或旧音频强制播放到指定分钟数。高保真模式保留原画布；AI 增强模式可增加必要页面。
        </p>
        {automatic[0] && (
          <details>
            <summary>查看本页将传给内容模型的生成要求（尚未调用模型）</summary>
            <pre>{withSceneContentDuration(automatic[0]).description}</pre>
          </details>
        )}
      </section>
      {fixtures.length > 0 && (
        <section>
          <label>
            原始课件{' '}
            <select value={selected} onChange={(event) => setSelected(Number(event.target.value))}>
              {fixtures.map((item, index) => (
                <option key={item.name} value={index}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <p>
            重新读取原始 WAV：{fixture.audioClips} 段音频，合计{' '}
            {formatPlaybackDuration(fixture.audioSeconds)}。改变目标不会改变已有音频。
          </p>
          {!error && <CourseDurationSummary stage={stage} scenes={fixture.scenes} />}
          <p>音频总长与完整播放时长分开统计；含未测量视频或白板的课件会显示尚未完成实测。</p>
        </section>
      )}
      <section>
        <h2>预算检查</h2>
        <p>
          {error ||
            `目标 ${minutes} 分钟 = ${minutes * 60} 秒；自动页面 ${automatic.length} 页；预算合计 ${automatic.reduce((sum, page) => sum + page.durationBudget!.targetSeconds, 0)} 秒。`}
        </p>
        <p>以下为新预算预览，不修改原始 JSON、声音或 reveal。答题与自由讨论不计入自动播放目标。</p>
        <details>
          <summary>查看页面预算（用于生成规划）</summary>
          <pre>
            {JSON.stringify(
              outlines.map((outline) => ({
                title: outline.title,
                type: outline.type,
                targetSeconds: outline.durationBudget?.targetSeconds ?? '自主活动，不计入',
              })),
              null,
              2,
            )}
          </pre>
        </details>
      </section>
      <section>
        <h2>真实生成测试</h2>
        <p>
          配置可用的模型与 TTS 后，在教师端生成一门新课程，填写20分钟或留空。生成结束后查看“目标 /
          实测 / 达标状态”。现有课程不会自动改成28分钟。
        </p>
      </section>
    </main>
  );
}

createRoot(document.getElementById('root')!).render(<Preview />);
