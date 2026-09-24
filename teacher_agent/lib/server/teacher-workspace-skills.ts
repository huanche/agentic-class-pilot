import fs from 'node:fs/promises';
import path from 'node:path';

export type TeacherWorkspaceSkill = {
  name: string;
  description: string;
  instructions: string;
};

function parseSkill(source: string): TeacherWorkspaceSkill | undefined {
  const match = source.match(/^---\s*\n([\s\S]*?)\n---\s*\n([\s\S]*)$/u);
  if (!match) return undefined;
  const name = match[1].match(/^name:\s*(.+)$/mu)?.[1]?.trim();
  const description = match[1].match(/^description:\s*(.+)$/mu)?.[1]?.trim();
  if (!name || !description) return undefined;
  return { name, description, instructions: match[2].trim() };
}

export async function loadTeacherWorkspaceSkills() {
  const root = path.join(process.cwd(), 'skills');
  const entries = await fs.readdir(root, { withFileTypes: true });
  const skills = await Promise.all(
    entries
      .filter((entry) => entry.isDirectory() && entry.name.startsWith('teacher-'))
      .map(async (entry) => {
        try {
          return parseSkill(await fs.readFile(path.join(root, entry.name, 'SKILL.md'), 'utf8'));
        } catch {
          return undefined;
        }
      }),
  );
  return skills.filter((skill): skill is TeacherWorkspaceSkill => Boolean(skill));
}
