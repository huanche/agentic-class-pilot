/** Platform runtime boundaries; standalone operation keeps upstream behavior. */
import { internalPlatformHeaders } from './platform-auth';

export function managesRuntimeSchema(): boolean {
  return !process.env.COURSE_DATABASE_SCHEMA?.trim()
    || process.env.COURSE_DATABASE_MANAGE_SCHEMA === 'true';
}

export function internalTeacherRequest(baseUrl: string, userId: string) {
  const platform = process.env.PLATFORM_AUTH_ENABLED === 'true';
  // Never send service credentials to a Host/X-Forwarded-Host supplied by a client.
  const origin = platform
    ? process.env.PLATFORM_TEACHER_INTERNAL_URL || process.env.TEACHER_URL
    : baseUrl;
  if (!origin) throw new Error('教师内部服务地址未配置（PLATFORM_TEACHER_INTERNAL_URL）');
  const url = new URL(origin);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) {
    throw new Error('教师内部服务地址配置无效');
  }
  return { baseUrl: origin.replace(/\/$/, ''), headers: internalPlatformHeaders(userId) };
}
