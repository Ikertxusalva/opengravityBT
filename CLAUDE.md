# OpenGravity — Multi-Agent Agentic System

Dashboard multi-agente con terminales Claude Code integradas y arquitectura híbrida (PC + Railway).

## Filosofía de Trabajo

### 1. Plan Mode por Defecto
- Entrar en plan mode para tareas no triviales (3+ pasos o decisiones de arquitectura).
- Si algo sale mal, PARAR y re-planificar — no seguir empujando.
- Escribir specs detallados antes de implementar para reducir ambigüedad.

### 2. Subagentes
- Usar subagentes para mantener el contexto principal limpio.
- Delegar investigación, exploración y análisis en paralelo a subagentes.
- Un task por subagente para ejecución enfocada.

### 3. Auto-Mejora Continua
- Tras CUALQUIER corrección del usuario: actualizar `tasks/lessons.md` con el patrón.
- Escribir reglas que prevengan repetir el mismo error.
- Revisar lessons al inicio de cada sesión relevante.

### 4. Verificar Antes de Dar por Hecho
- Nunca marcar una tarea como completa sin demostrar que funciona.
- Diff entre main y tus cambios cuando sea relevante.
- Preguntarte: "¿Un senior engineer aprobaría esto?"

### 5. Elegancia sin Over-Engineering
- Si un fix se siente hacky: implementar la solución elegante.
- Para fixes simples y obvios: no sobre-pensar, ejecutar.
- Cuestionar tu propio trabajo antes de presentarlo.

### 6. Bug Fixing Autónomo
- Ante un bug report: arreglarlo directamente. No pedir guía.
- Apuntar a logs, errores, tests que fallan — y resolverlos.
- Zero context switching requerido del usuario.

## Reglas de Trabajo
- **Idioma**: Responder siempre en **español**.
- **Acción Directa**: Implementa, testea y commitea sin análisis innecesarios para tareas simples.
- **Auto-Commit**: Hacer commit y push tras cada cambio significativo.
- **Simplicidad**: Cada cambio lo más simple posible. Impactar el mínimo código.
- **No Laziness**: Encontrar root causes. Nada de fixes temporales. Estándares de senior dev.
- **Entorno Híbrido**:
  - El **Backend** (Python/FastAPI/Postgres) vive en Railway.
  - El **Frontend** (Electron/Nextron) vive en el PC local.
  - Comunicación vía WebSocket: `wss://chic-encouragement-production.up.railway.app/ws`

## Task Management
1. **Plan First**: Para tareas complejas, escribir plan en `tasks/todo.md` con items checkeables.
2. **Track Progress**: Marcar items como completos según avanzas.
3. **Capture Lessons**: Actualizar `tasks/lessons.md` tras correcciones del usuario.

## Memoria y Contexto
- El contexto de sesiones anteriores se guarda en `.claude/agent-contexts/`.
- Lessons aprendidas persisten en `tasks/lessons.md`.
- Si necesitas detalle sobre agentes, APIs o infraestructura: leer `opengravity-app/README.md` o preguntar al sistema.

## Comandos Principales

```bash
# ── Frontend (App de Escritorio) ──────────────────────────────────────────
cd opengravity-app
npm install        # Instalar dependencias
npm run dev        # Iniciar modo desarrollo (Nextron)
npm run build      # Construir ejecutable

# ── Backend (Cloud / Railway) ─────────────────────────────────────────────
# Los cambios en opengravity-app/cloud se despliegan automáticamente al hacer push a GitHub.

# Logs del servidor (vía Railway CLI si está instalado):
railway logs
```

## Estructura del Proyecto

```
OpenGravity/
├── CLAUDE.md              # Este archivo — reglas del proyecto
├── tasks/                 # Task management y lessons learned
│   ├── todo.md            # Plan actual con checkboxes
│   └── lessons.md         # Errores corregidos → reglas permanentes
├── launch.bat             # Lanzador rápido (PC)
├── opengravity-app/       # Core de la aplicación
│   ├── cloud/             # Backend Python (FastAPI + Docker + Railway)
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── server.py
│   ├── main/              # Proceso Principal Electron (TypeScript)
│   ├── renderer/          # Interfaz Next.js (React + Tailwind)
│   ├── archive/           # Agentes deshabilitados (backup)
│   └── app/               # Código compilado de Electron
└── service-account.json   # Credenciales Firebase (NO SUBIR)
```

## Stack Tecnológico
- **Frontend**: Nextron (Next.js + Electron), XTerm.js, WebSockets.
- **Backend Cloud**: FastAPI, SQLAlchemy, PostgreSQL, Docker.
- **Agentes**: Claude Code (CLI) integrado vía `node-pty`.

## Notas de Estilo
- Usar un diseño oscuro (Dark Mode), premium y minimalista (estilo RBI).
- Priorizar la fluidez en las terminales y la estabilidad de la conexión cloud.
