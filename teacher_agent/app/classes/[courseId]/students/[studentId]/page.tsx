import { StudentLearningDetail } from '../../roster';

export default async function StudentPage({ params, searchParams }: {
  params: Promise<{ courseId: string; studentId: string }>;
  searchParams: Promise<{ lesson?: string }>;
}) {
  const { courseId, studentId } = await params;
  const { lesson } = await searchParams;
  return <StudentLearningDetail courseId={courseId} studentId={studentId} lessonId={lesson} />;
}
