"""
Bot de Telegram con Ollama (gratis, local, sin API key).

Setup:
1. Asegúrate de que Ollama está corriendo: `ollama serve`
2. Añade TELEGRAM_BOT_TOKEN a tu .env
3. Ejecuta: uv run python moondev/telegram_bot.py

Para cambiar el modelo: edita OLLAMA_MODEL abajo.
"""

import os
import logging
from collections import defaultdict

import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")
MAX_HISTORY = 20  # mensajes por chat

SYSTEM_PROMPT = """Eres un asistente de trading e inversiones especializado en:
- Análisis de estrategias de trading algorítmico
- Backtesting con Python (backtesting.py, pandas-ta)
- Análisis de criptomonedas y mercados financieros
- Código Python para finanzas cuantitativas

Responde siempre en español. Sé conciso y directo."""

# Historial por chat: {chat_id: [{"role": ..., "content": ...}]}
conversation_history: dict[int, list] = defaultdict(list)


def chat_with_ollama(messages: list) -> str:
    """Llama a Ollama y devuelve la respuesta."""
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
        "stream": False,
    }
    with httpx.Client(timeout=120.0) as client:
        resp = client.post(f"{OLLAMA_HOST}/api/chat", json=payload)
        resp.raise_for_status()
        return resp.json()["message"]["content"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    conversation_history[chat_id].clear()
    await update.message.reply_text(
        f"Hola! Soy tu asistente de trading (modelo: `{OLLAMA_MODEL}`).\n\n"
        "Comandos:\n"
        "• /start — reiniciar conversación\n"
        "• /clear — limpiar historial\n"
        "• /model — ver modelo activo",
        parse_mode="Markdown",
    )


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conversation_history[update.effective_chat.id].clear()
    await update.message.reply_text("Historial limpiado.")


async def model_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"Modelo: `{OLLAMA_MODEL}`\nHost: `{OLLAMA_HOST}`", parse_mode="Markdown"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_text = update.message.text

    await update.message.chat.send_action("typing")

    history = conversation_history[chat_id]
    history.append({"role": "user", "content": user_text})

    if len(history) > MAX_HISTORY:
        conversation_history[chat_id] = history[-MAX_HISTORY:]

    try:
        reply = chat_with_ollama(conversation_history[chat_id])
        conversation_history[chat_id].append({"role": "assistant", "content": reply})

        # Telegram: máx 4096 chars por mensaje
        for i in range(0, len(reply), 4096):
            await update.message.reply_text(reply[i : i + 4096])

    except httpx.ConnectError:
        await update.message.reply_text(
            "No puedo conectar con Ollama. ¿Está corriendo?\n`ollama serve`",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(f"Error: {str(e)[:200]}")


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN no configurado en .env")

    logger.info(f"Iniciando bot con Ollama/{OLLAMA_MODEL}...")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("model", model_info))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot iniciado. Esperando mensajes...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
