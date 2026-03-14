import { dialog, BrowserWindow } from 'electron';
import { AuditLog } from './audit';

export interface TransactionRequest {
  agentId: string;
  type: 'TOKEN_TRANSFER' | 'SWAP' | 'CONTRACT_INTERACTION';
  details: {
    symbol?: string;
    amount?: number;
    destination?: string;
    action?: string;
  };
}

export class WalletGuard {
  // Hardcoded limits
  private static readonly MAX_SOL_PER_TX = 0.5;
  private static readonly MAX_USD_PER_TX = 100.0;

  static async requestApproval(window: BrowserWindow, request: TransactionRequest): Promise<boolean> {
    const { agentId, type, details } = request;

    // 1. Log request
    AuditLog.log({
      agent: agentId,
      action: 'WALLET_REQUEST',
      details: `Agent requested ${type}: ${JSON.stringify(details)}`,
      level: 'WARNING',
      result: 'PENDING',
    });

    // 2. Check hard limits (simplified)
    if (details.amount && details.amount > this.MAX_SOL_PER_TX && (details.symbol === 'SOL' || !details.symbol)) {
      AuditLog.log({
        agent: agentId,
        action: 'WALLET_BLOCKED',
        details: `Transaction blocked: Amount ${details.amount} exceeds limit ${this.MAX_SOL_PER_TX} SOL`,
        level: 'CRITICAL',
        result: 'BLOCKED',
      });
      
      dialog.showErrorBox(
        'Seguridad: Transacción Bloqueada',
        `El agente ${agentId} intentó transferir ${details.amount} SOL, lo cual excede el límite de seguridad de ${this.MAX_SOL_PER_TX} SOL.`
      );
      return false;
    }

    // 3. Show manual approval dialog
    const result = await dialog.showMessageBox(window, {
      type: 'warning',
      title: 'Aprobación de Transacción Requerida',
      message: `El agente "${agentId}" solicita realizar una transacción.`,
      detail: `Tipo: ${type}\nDetalles: ${JSON.stringify(details, null, 2)}\n\n¿Deseas aprobar esta operación?`,
      buttons: ['Bloquear', 'Aprobar'],
      defaultId: 0,
      cancelId: 0,
    });

    const approved = (result.response === 1);

    // 4. Log result
    AuditLog.log({
      agent: agentId,
      action: approved ? 'WALLET_APPROVED' : 'WALLET_REJECTED',
      details: approved ? 'User approved transaction' : 'User rejected transaction',
      level: approved ? 'INFO' : 'WARNING',
      result: approved ? 'ALLOWED' : 'BLOCKED',
    });

    return approved;
  }
}
