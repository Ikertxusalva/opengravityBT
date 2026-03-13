import { Bot } from 'grammy';
import { ENV } from '../src/config/index.js';

const bot = new Bot(ENV.TELEGRAM_BOT_TOKEN);
const url = process.argv[2];

if (!url) {
    console.error("❌ Por favor, proporciona la URL de tu despliegue de Vercel (ej: https://tu-bot.vercel.app/api/webhook)");
    process.exit(1);
}

async function main() {
    console.log(`Configurando webhook a: ${url}`);
    await bot.api.setWebhook(url);
    console.log("✅ Webhook configurado exitosamente en Telegram.");
}

main().catch(console.error);
