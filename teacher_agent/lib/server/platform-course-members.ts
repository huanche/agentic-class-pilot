import { NextRequest, NextResponse } from 'next/server';
import { isPlatformAuthEnabled, resolveTeacherId } from './platform-course-bridge';

type PlatformMember = {
  studentId: string;
  name: string;
  email?: string;
  enrolledAt?: string;
};

/** Read the authoritative platform enrollment roster. Never persist a copy. */
export async function platformCourseMembers(
  request: NextRequest,
  courseId: string,
): Promise<PlatformMember[] | undefined> {
  return (await platformCourseRoster(request, courseId))?.members;
}

export type PlatformRoster = {
  members: PlatformMember[];
  /** 平台解析后的课程 UUID（legacy nanoid 课程也在此归一）；学情聚合 SQL 用它查 student schema。 */
  platformCourseId?: string;
};

export async function platformCourseRoster(
  request: NextRequest,
  courseId: string,
): Promise<PlatformRoster | undefined> {
  if (!isPlatformAuthEnabled()) return undefined;
  const teacherId = resolveTeacherId(request, undefined);
  if (!teacherId) throw new Error('请先登录平台');
  const response = await fetch(
    `${process.env.PLATFORM_AUTH_URL}/api/v1/internal/teacher/courses/${encodeURIComponent(courseId)}/members`,
    {
      headers: {
        'X-Teacher-Service-Key': process.env.PLATFORM_SERVICE_KEY || '',
        'X-Platform-Subject': teacherId,
      },
      cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(5000),
    },
  );
  const data = await response.json() as { detail?: string; members?: PlatformMember[]; courseId?: string };
  if (!response.ok) throw new Error(data.detail || '读取学生名单失败');
  return { members: data.members ?? [], platformCourseId: data.courseId };
}

export async function platformCourseMembersResponse(request: NextRequest, courseId: string) {
  try {
    return NextResponse.json({ members: await platformCourseMembers(request, courseId) ?? [] });
  } catch (error) {
    const message = error instanceof Error ? error.message : '读取学生名单失败';
    return NextResponse.json({ error: message }, { status: message === '请先登录平台' ? 401 : 502 });
  }
}
