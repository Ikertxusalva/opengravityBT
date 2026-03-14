/**
 * Capa 6 — Detector de prompt injection en contenido web externo.
 */

import { log as auditLog } from './audit';

interface InjectionPattern {
  regex: RegExp;
  label: string;
}

const INJECTION_PATTERNS: InjectionPattern[] = [
  // Instrucciones directas de overriding
  { regex: /ignore\s+(all\s+)?(previous|prior|your|above|these)\s+(instructions?|rules?|guidelines?|constraints?|prompts?)/gi, label: 'override_instructions' },
  { regex: /disregard\s+(\w+\s+){0,3}(instructions?|rules?|guidelines?|constraints?)/gi, label: 'override_instructions' },
  { regex: /forget\s+(everything|all\s+previous|your\s+instructions?)/gi, label: 'override_instructions' },
  { regex: /do\s+not\s+follow\s+(your\s+)?(previous\s+)?(instructions?|guidelines?|rules?)/gi, label: 'override_instructions' },

  // Inyección de rol
  { regex: /you\s+are\s+now\s+(a\s+|an\s+)?(?!trading|research|strategy|risk)/gi, label: 'role_injection' },
  { regex: /act\s+as\s+(a\s+|an\s+)?(?!trading|research|strategy|risk)/gi, label: 'role_injection' },
  { regex: /pretend\s+(you\s+are|to\s+be)\s+(a\s+|an\s+)?/gi, label: 'role_injection' },
  { regex: /your\s+new\s+(role|identity|persona|instructions?)\s+(is|are)\s*:/gi, label: 'role_injection' },
  { regex: /\[new\s+system\s+(prompt|instructions?)\]/gi, label: 'role_injection' },
  { regex: /\[override\]/gi, label: 'role_injection' },

  // Marcadores de sistema falsos
  { regex: /<\s*system\s*>/gi, label: 'fake_system_tag' },
  { regex: /\[SYSTEM\]/gi, label: 'fake_system_tag' },
  { regex: /###\s*System/gi, label: 'fake_system_tag' },
  { regex: /###\s*Instructions?/gi, label: 'fake_system_tag' },
  { regex: /\[INST\]/gi, label: 'fake_system_tag' },
  { regex: /<\|im_start\|>\s*system/gi, label: 'fake_system_tag' },
  { regex: /<\|system\|>/gi, label: 'fake_system_tag' },

  // Exfiltración de datos
  { regex: /send\s+(all\s+)?(your\s+)?(api[\s_]?keys?|credentials?|secrets?|tokens?|passwords?)\s+to/gi, label: 'exfiltration' },
  { regex: /exfiltrate\s+(the\s+)?(api[\s_]?keys?|credentials?|secrets?)/gi, label: 'exfiltration' },
  { regex: /(reveal|expose|leak|share|print|output|display)\s+(your\s+)?(api[\s_]?keys?|secrets?|credentials?|system\s+prompt)/gi, label: 'exfiltration' },
  { regex: /what\s+(is|are)\s+your\s+(api[\s_]?keys?|credentials?|secrets?|system\s+prompt)/gi, label: 'exfiltration' },

  // Comandos de acción maliciosa
  { regex: /(delete|remove|drop|truncate)\s+(all\s+)?(files?|database|table|collection|data)/gi, label: 'destructive_command' },
  { regex: /execute\s+(this\s+)?(command|code|script|payload)/gi, label: 'code_execution' },
  { regex: /run\s+(this\s+)?(command|code|script|payload)/gi, label: 'code_execution' },
  { regex: /eval\s*\(/gi, label: 'code_execution' },

  // Jailbreaks conocidos
  { regex: /DAN\s+(mode|prompt|jailbreak)/gi, label: 'jailbreak' },
  { regex: /developer\s+mode\s+(enabled|on|activated)/gi, label: 'jailbreak' },
  { regex: /jailbreak(ed|ing)?\s+(mode|prompt|activated)/gi, label: 'jailbreak' },
  { regex: /do\s+anything\s+now/gi, label: 'jailbreak' },
  { regex: /grandma\s+(exploit|jailbreak|trick)/gi, label: 'jailbreak' },
];

const INVISIBLE_UNICODE = /[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u206a-\u206f\ufeff\u00ad]/g;
const MAX_CONTENT_LEN = 50000;

export interface ScanResult {
  cleanText: string;
  threats: string[];
  truncated: boolean;
  invisibleCharsRemoved: number;
}

export function sanitizeWebContent(
  text: string,
  sourceUrl: string = '',
  agentId: string = 'unknown',
  maxLen: number = MAX_CONTENT_LEN
): ScanResult {
  let threats: string[] = [];
  let currentText = text;

  // 1. Eliminar caracteres Unicode invisibles
  const originalLen = currentText.length;
  currentText = currentText.replace(INVISIBLE_UNICODE, '');
  const invisibleRemoved = originalLen - currentText.length;

  // 2. Normalizar Unicode (NFC)
  currentText = currentText.normalize('NFC');

  // 3. Detectar patrones de injection
  for (const pattern of INJECTION_PATTERNS) {
    if (pattern.regex.test(currentText)) {
      if (!threats.includes(pattern.label)) {
        threats.push(pattern.label);
      }
    }
  }

  // 4. Si hay amenazas: redactar los fragmentos peligrosos
  if (threats.length > 0) {
    for (const pattern of INJECTION_PATTERNS) {
      currentText = currentText.replace(pattern.regex, '[REDACTED:INJECTION_ATTEMPT]');
    }
  }

  // 5. Truncar si es demasiado largo
  let truncated = false;
  if (currentText.length > maxLen) {
    currentText = currentText.substring(0, maxLen) + '\n...[contenido truncado por límite de seguridad]';
    truncated = true;
  }

  // 6. Audit log
  if (threats.length > 0 || invisibleRemoved > 0) {
    try {
      const details = `threats=${threats.join(',')} invisible_chars_removed=${invisibleRemoved}`;
      auditLog(
        agentId,
        'web_content_scan',
        sourceUrl || '(unknown)',
        threats.length > 0 ? 'blocked' : 'ok',
        details
      );
    } catch (e) {
      // Ignorar fallos de audit log
    }
  }

  return {
    cleanText: currentText,
    threats,
    truncated,
    invisibleCharsRemoved: invisibleRemoved,
  };
}
