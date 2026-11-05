import { ChevronLeft, ChevronRight, Maximize, Minimize } from 'lucide-react';
import styles from './course-video-player.module.css';

/** One course pagination bar for videos, activities, quizzes and projects. */
export function CoursePageNavigation({
  index,
  total,
  fullscreen,
  onPrevious,
  onNext,
  onFullscreen,
}: {
  index: number;
  total: number;
  fullscreen: boolean;
  onPrevious: () => void;
  onNext: () => void;
  onFullscreen: () => void;
}) {
  return (
    <div className={styles.courseNavigation} data-course-navigation>
      <nav aria-label="课程翻页" className={styles.pageButtons}>
        <button
          type="button"
          className={styles.pageButton}
          disabled={index === 0}
          onClick={onPrevious}
          aria-label="上一页"
        >
          <ChevronLeft size={16} />
          <span>上一页</span>
        </button>
        <button
          type="button"
          className={styles.pageButton}
          disabled={index >= total - 1}
          onClick={onNext}
          aria-label="下一页"
        >
          <span>下一页</span>
          <ChevronRight size={16} />
        </button>
        <span className={styles.pageCount} aria-live="polite">
          {index + 1} / {total}
        </span>
      </nav>
      <button
        type="button"
        className={styles.activityButton}
        onClick={onFullscreen}
        aria-label={fullscreen ? '退出全屏' : '全屏'}
      >
        {fullscreen ? <Minimize size={19} /> : <Maximize size={19} />}
      </button>
    </div>
  );
}
