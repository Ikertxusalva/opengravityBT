# OpenGravity — Multi-Agent Agentic System

Dashboard multi-agente con terminales Claude Code + arquitectura híbrida (PC + Railway).

## Reglas de Trabajo
- **Idioma**: Siempre en **español**.
- **Acción Directa**: Implementa, testea y commitea sin análisis innecesarios.
- **Auto-Commit**: Commit + push tras cada cambio significativo. Sin pedir confirmación.
- **Simplicidad**: Mínimo código impactado. Sin over-engineering.
- **No Laziness**: Root causes, no fixes temporales. Estándares senior dev.
- **Bugs**: Arreglarlos directamente — logs, errores, tests. Sin pedir guía.
- **Plan Mode**: Para tareas con 3+ pasos o decisiones de arquitectura.
- **Lessons**: Tras CUALQUIER corrección del usuario → actualizar `tasks/lessons.md`.
- **Archivos grandes (>300 líneas)**: NUNCA reescribir completos con Write. Usar SIEMPRE Edit/str_replace para cambios parciales. Si el refactor es grande, hacerlo en secciones con commit entre cada una. Archivos críticos: `index.tsx`, `server.py`, `pty-manager.ts`.

## Entorno
- **Frontend**: Electron/Nextron (PC local) — `cd opengravity-app && npm run dev`
- **Backend**: FastAPI/Postgres en Railway — push a GitHub = deploy automático
- **WebSocket**: `wss://chic-encouragement-production.up.railway.app/ws`
- **Logs Railway**: `railway logs`

## Estructura
```
OpenGravity/
├── tasks/          # todo.md (plan), lessons.md (errores → reglas)
├── opengravity-app/
│   ├── cloud/      # Backend Python (FastAPI + Docker + Railway)
│   ├── main/       # Proceso Principal Electron (TypeScript)
│   ├── renderer/   # Interfaz Next.js (React + Tailwind)
│   └── archive/    # Agentes deshabilitados
└── service-account.json  # Firebase (NO SUBIR)
```

## Stack
- Frontend: Nextron, XTerm.js, WebSockets
- Backend: FastAPI, SQLAlchemy, PostgreSQL, Docker
- Agentes: Claude Code CLI vía node-pty

## Estilo
- Dark Mode, premium y minimalista (estilo RBI).
- Priorizar fluidez de terminales y estabilidad cloud.

## Contexto y Memoria
- Sesiones anteriores: `.claude/agent-contexts/`
- Lessons: `tasks/lessons.md`
- Detalle de infra: `opengravity-app/README.md`
