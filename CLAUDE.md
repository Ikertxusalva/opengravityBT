# OpenGravity — Multi-Agent Agentic System

Dashboard multi-agente con terminales Claude Code integradas y arquitectura híbrida (PC + Railway).

## Memoria y Contexto
- El contexto de sesiones anteriores se guarda automáticamente en `.claude/agent-contexts/`.
- Al iniciar, **lee tu archivo de contexto** para continuar donde quedaste:
  - Agente principal: `.claude/agent-contexts/claude-main.md`
  - Otros agentes: `.claude/agent-contexts/{agent-id}.md`
- Si necesitas detalle sobre agentes, APIs o infraestructura: leer `opengravity-app/README.md` (si existe) o preguntar al sistema.
- **IMPORTANTE**: No busques memorias al inicio. Tu contexto ya está en los archivos del proyecto.

## Reglas de Trabajo
- **Idioma**: Responder siempre en **español**.
- **Acción Directa**: Implementa, testea y commitea sin análisis innecesarios para tareas simples.
- **Auto-Commit**: Hacer commit y push tras cada cambio significativo.
- **Entorno Híbrido**:
  - El **Backend** (Python/FastAPI/Postgres) vive en Railway.
  - El **Frontend** (Electron/Nextron) vive en el PC local.
  - Comunicación vía WebSocket: `wss://chic-encouragement-production.up.railway.app/ws`

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
├── launch.bat             # Lanzador rápido (PC)
├── opengravity-app/       # Core de la aplicación
│   ├── cloud/             # Backend Python (FastAPI + Docker + Railway)
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── server.py
│   ├── main/              # Proceso Principal Electron (TypeScript)
│   ├── renderer/          # Interfaz Next.js (React + Tailwind)
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
