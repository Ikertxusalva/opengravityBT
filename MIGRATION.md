# Guía de Migración a Railway (Bot Persistente) 🚀

Para que OpenGravity responda **al instante**, lo vamos a mover de Vercel (que se "duerme") a Railway (que está siempre encendido).

### 1. Preparación en GitHub
Sube este código a un repositorio privado de **GitHub**.

### 2. Despligue en Railway
1. Haz clic en **"New Project"** -> **"Deploy from GitHub repo"**.
2. Elige tu repositorio y la rama `main`.

### 3. Variables de Entorno (IMPORTANTE)
Verás una pestaña llamada **"Variables"**. Tienes que añadir las mismas de tu archivo `.env`:
- `TELEGRAM_BOT_TOKEN`: Tu token de Telegram.
- `TELEGRAM_ALLOWED_USER_IDS`: Tu ID de usuario (separado por comas si hay varios).
- `GROQ_API_KEY`: Tu API key de Groq.
- `GOOGLE_APPLICATION_CREDENTIALS`: Aquí pega **TODO EL CONTENIDO** del archivo `service-account.json` (el JSON de Firebase).

### ¿Qué hemos mejorado?
- **Sin esperas**: El bot estará siempre vivo. Notarás que responde muchísimo más rápido.
- **Sin Webhooks**: Ahora usa el modo "Polling", lo que elimina errores de conexión.
- **Precios Reales**: Acabo de actualizar el código para que, cuando preguntes por crypto (como SOL o BTC), use la API real de **CoinGecko** y te de el precio exacto del mercado.

¡Una vez que veas el "✅ Success" en Railway, pruébalo con un *"¿Cómo ves el precio de Solana?"* y verás la diferencia! 🚀
