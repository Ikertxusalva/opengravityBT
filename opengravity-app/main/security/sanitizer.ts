/**
 * Capa 3 — Sanitizador de código generado por agentes antes de ejecución.
 */

interface BlockedPattern {
  regex: RegExp;
  label: string;
}

const BLOCKED_PATTERNS: BlockedPattern[] = [
  // Shell execution
  { regex: /os\s*\.\s*system\s*\(/g, label: 'os.system()' },
  { regex: /subprocess\s*\.\s*(run|Popen|call|check_output)\s*\(/g, label: 'subprocess.*()' },
  { regex: /child_process\s*\.\s*(exec|spawn|execSync|spawnSync)\s*\(/g, label: 'child_process.*()' },
  
  // Code execution
  { regex: /\beval\s*\(/g, label: 'eval()' },
  { regex: /\bexec\s*\(/g, label: 'exec()' },
  // Node specific exec
  { regex: /new\s+Function\s*\(/g, label: 'new Function()' },
  
  // Dynamic imports / Requires
  { regex: /\brequire\s*\(\s*['"](child_process|fs|os|path|process)['"]\s*\)/g, label: 'sensitive require()' },
  { regex: /import\s*\(\s*['"](child_process|fs|os|path|process)['"]\s*\)/g, label: 'sensitive dynamic import()' },
  
  // File system destructivo (Sensitive files)
  { regex: /['"].*\.env/g, label: '.env access attempt' },
  { regex: /fs\s*\.\s*(rmdir|unlink|rm|truncate|writeFile|appendFile)\s*\(/g, label: 'destructive fs.*()' },
  { regex: /fsPromises\s*\.\s*(rmdir|unlink|rm|truncate|writeFile|appendFile)\s*\(/g, label: 'destructive fsPromises.*()' },
];

export interface ValidationResult {
  valid: boolean;
  reason: string;
}

/**
 * Valida que el código generado no contenga patrones peligrosos.
 */
export function validateCode(code: string): ValidationResult {
  for (const pattern of BLOCKED_PATTERNS) {
    if (pattern.regex.test(code)) {
      return {
        valid: false,
        reason: `Blocked pattern detected: ${pattern.label}`,
      };
    }
  }
  return { valid: true, reason: '' };
}
