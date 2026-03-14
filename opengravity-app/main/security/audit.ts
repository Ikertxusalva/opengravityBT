import * as fs from 'fs';
import * as path from 'path';
import { app } from 'electron';

export interface AuditEntry {
  timestamp: string;
  agent?: string;
  action: string;
  details: string;
  level: 'INFO' | 'WARNING' | 'CRITICAL';
  result: 'ALLOWED' | 'BLOCKED' | 'PENDING';
}

export class AuditLog {
  private static logPath: string = path.join(process.cwd(), 'logs', 'security.jsonl');

  static initialize() {
    const logDir = path.dirname(this.logPath);
    if (!fs.existsSync(logDir)) {
      fs.mkdirSync(logDir, { recursive: true });
    }
  }

  static async log(entry: Omit<AuditEntry, 'timestamp'>) {
    const fullEntry: AuditEntry = {
      timestamp: new Date().toISOString(),
      ...entry,
    };

    try {
      fs.appendFileSync(this.logPath, JSON.stringify(fullEntry) + '\n', 'utf-8');
    } catch (e) {
      console.error('[AuditLog] Failed to write log:', e);
    }
  }
}
