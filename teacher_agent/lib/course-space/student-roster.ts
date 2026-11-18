export type RosterEntry = {
  studentNumber: string; name: string; major: string; grade: string; gender: string;
  studentId: string | null;
};
export type RosterMember = { studentId: string; name: string; email?: string | null };
export type RosterDirectory = { entries: RosterEntry[]; members: RosterMember[] };

const normalizeName = (name: string) => name.normalize('NFKC').replace(/\s+/g, '').trim();

/** 只建议唯一姓名匹配，教师确认后才写入平台；不猜测昵称或重名。 */
export function suggestRosterLinks(imported: RosterEntry[], saved: RosterEntry[], members: RosterMember[]) {
  const nameCounts = new Map<string, number>();
  for (const row of imported) {
    const name = normalizeName(row.name);
    nameCounts.set(name, (nameCounts.get(name) ?? 0) + 1);
  }
  const result = imported.map(row => {
    const old = saved.find(item => item.studentNumber === row.studentNumber);
    const matches = members.filter(member => normalizeName(member.name) === normalizeName(row.name));
    return { ...row, grade: row.grade || old?.grade || '', studentId: old ? old.studentId :
      (matches.length === 1 && nameCounts.get(normalizeName(row.name)) === 1 ? matches[0].studentId : null) };
  });
  const retained = saved.filter(row => !imported.some(item => item.studentNumber === row.studentNumber));
  const all = [...result, ...retained];
  return all.map(row => row.studentId && !saved.some(old => old.studentNumber === row.studentNumber) &&
    all.filter(item => item.studentId === row.studentId).length > 1
    ? { ...row, studentId: null } : row);
}
