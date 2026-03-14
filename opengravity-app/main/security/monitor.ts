// eslint-disable-next-line @typescript-eslint/no-var-requires
const notifier = require('node-notifier') as {
  notify(options: { title: string; message: string; sound?: boolean; wait?: boolean }): void;
};
import { AuditEntry, AuditLog } from './audit';

export class SecurityMonitor {
  private static consecutiveRejections: number = 0;
  private static readonly MAX_REJECTIONS = 3;

  static async notifyAnomalousBehavior(event: string) {
    notifier.notify({
      title: 'OpenGravity Security Alert',
      message: event,
      sound: true,
      wait: true,
    });
  }

  static async handleAuditEntry(entry: AuditEntry) {
    // Detect patterns
    if (entry.action === 'WALLET_REJECTED') {
      this.consecutiveRejections++;
      if (this.consecutiveRejections >= this.MAX_REJECTIONS) {
        this.notifyAnomalousBehavior('Multiple rejected transactions. Possible malicious agent behavior detected.');
        this.consecutiveRejections = 0; // Reset
      }
    } else if (entry.action === 'WALLET_APPROVED') {
      this.consecutiveRejections = 0; // Reset on success
    }

    if (entry.level === 'CRITICAL') {
      this.notifyAnomalousBehavior(`Critical Security Event: ${entry.details}`);
    }
  }
}
