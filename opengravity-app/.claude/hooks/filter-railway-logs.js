/**
 * Hook: filter railway logs output to errors/warnings only.
 * Reduces token consumption when Claude reads Railway deployment logs.
 *
 * PreToolUse on Bash — intercepts `railway logs` commands and appends
 * a filter so Claude only sees relevant lines instead of full log dumps.
 */
let input = '';
process.stdin.setEncoding('utf-8');
process.stdin.on('data', chunk => { input += chunk; });
process.stdin.on('end', () => {
  try {
    const data = JSON.parse(input);
    const cmd = (data?.tool_input?.command || '').trim();

    // Only intercept bare `railway logs` (not already filtered)
    if (/railway\s+logs?(\s|$)/i.test(cmd) && !cmd.includes('|') && !cmd.includes('findstr') && !cmd.includes('grep')) {
      const filtered =
        `(${cmd}) 2>&1 | findstr /R /I /C:"error" /C:"warn" /C:"fail" /C:"critical" /C:"exception" /C:"traceback" 2>nul` +
        ` || echo "[railway logs: no errors or warnings found]"`;
      process.stdout.write(JSON.stringify({ hookSpecificOutput: { command: filtered } }));
    }
  } catch {
    // Parse error — let the command through unmodified
  }
  // Exiting without output = no modification, tool runs normally
});
