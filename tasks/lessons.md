# Lessons Learned

Archivo de auto-mejora. Cada corrección del usuario se documenta aquí como regla para no repetir el mismo error.

---

## Reglas Aprendidas

### [2026-03-14] Liquidaciones HyperLiquid son parciales
- Las liquidaciones de HL vía `recentTrades` son trades del sistema (hash=0x000...0), parciales de $50-$1000.
- No filtrar por $10K+ porque nunca aparecerán. Umbral correcto: $500.

### [2026-03-14] No preguntar, actuar
- El usuario quiere acción directa: commit y push sin pedir confirmación.
- "No me tienes que preguntar" — implementar, testear, commitear.

### [2026-03-14] Colores de liquidaciones
- LONG = verde (#00e676), SHORT = rojo (#ff4455). Siempre.

### [2026-03-14] GitHub Push Protection
- Nunca commitear archivos con API keys. Verificar antes de hacer `git add`.
- webapp/ contiene keys hardcodeadas — no subir a GitHub.
