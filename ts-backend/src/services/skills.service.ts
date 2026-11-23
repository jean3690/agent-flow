import { Injectable } from '@nestjs/common';
import fs from 'fs';
import path from 'path';
import { config } from '../config';

export interface SkillInfo {
  name: string;
  description: string;
  content: string;
  references: string[];
  dir: string | null;
}

@Injectable()
export class SkillsService {
  private readonly skills = new Map<string, SkillInfo>();

  constructor() {
    this.load();
  }

  private load(): void {
    const root = config.skillsPath;
    if (!fs.existsSync(root)) return;
    for (const dir of fs.readdirSync(root)) {
      const full = path.join(root, dir);
      const file = path.join(full, 'SKILL.md');
      if (!fs.statSync(full).isDirectory() || !fs.existsSync(file)) continue;
      const raw = fs.readFileSync(file, 'utf8');
      const match = raw.match(/^---\s*\n([\s\S]*?)\n---\s*\n([\s\S]*)$/);
      if (!match) continue;
      const metadata: Record<string, string> = {};
      for (const line of match[1].split('\n')) {
        const index = line.indexOf(':');
        if (index <= 0) continue;
        let value = line.slice(index + 1).trim();
        if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
          value = value.slice(1, -1);
        }
        metadata[line.slice(0, index).trim()] = value;
      }
      if (!metadata.name) continue;
      const referenceDir = path.join(full, 'reference');
      const references = fs.existsSync(referenceDir)
        ? fs.readdirSync(referenceDir).filter((f) => f.endsWith('.md')).map((f) => f.slice(0, -3)).sort()
        : [];
      this.skills.set(metadata.name, {
        name: metadata.name,
        description: metadata.description || '',
        content: match[2].trim(),
        references,
        dir: full,
      });
    }
  }

  summaries(): any[] {
    return [...this.skills.values()]
      .map(({ name, description }) => ({ name, description }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }

  get(name: string): SkillInfo | undefined {
    return this.skills.get(name);
  }

  fullContent(name: string): string {
    const skill = this.skills.get(name);
    if (!skill) throw new Error(`Skill not found: ${name}`);
    const parts = [`# ${skill.name}\n\n`, `${skill.content}\n\n`];
    if (skill.references.length) {
      parts.push('## 可用的参考文档\n');
      skill.references.forEach((ref) => parts.push(`- ${ref}\n`));
      parts.push('\n调用 load_skill_reference 函数获取详细内容。\n');
    }
    return parts.join('');
  }

  loadReference(skillName: string, referenceName: string): string {
    const skill = this.skills.get(skillName);
    if (!skill) throw new Error(`Skill not found: ${skillName}`);
    if (!/^[a-zA-Z0-9._-]+$/.test(referenceName)) throw new Error(`Invalid reference name: ${referenceName}`);
    if (!skill.references.includes(referenceName) || !skill.dir) {
      throw new Error(`Reference not found in skill: ${referenceName}`);
    }
    return fs.readFileSync(path.join(skill.dir, 'reference', `${referenceName}.md`), 'utf8');
  }

  allReferences(skillName: string): Record<string, string> {
    const skill = this.skills.get(skillName);
    if (!skill) return {};
    const result: Record<string, string> = {};
    for (const ref of skill.references) {
      try {
        result[ref] = this.loadReference(skillName, ref);
      } catch {
        // ignore unreadable references
      }
    }
    return result;
  }
}
