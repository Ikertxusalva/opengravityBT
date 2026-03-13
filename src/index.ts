import { bot } from './bot/index.js';
import { ENV } from './config/index.js';

import http from 'http';

async function main() {
    console.log("🚀 Iniciando OpenGravity en modo Persistente...");
    console.log(`Whitelist activada para IDs: ${ENV.TELEGRAM_ALLOWED_USER_IDS.join(', ')}`);

    // --- Tiny HTTP Server for Koyeb/Health-checks ---
    const PORT = process.env.PORT || 3000;
    http.createServer((req, res) => {
        res.writeHead(200, { 'Content-Type': 'text/plain' });
        res.end('OpenGravity is Alive');
    }).listen(PORT, () => {
        console.log(`📡 Servidor de salud escuchando en puerto ${PORT}`);
    });

    // Railway/Koyeb needs to drop Vercel's webhook to work in polling mode
    console.log("🧹 Limpiando configuraciones de webhooks...");
    await bot.api.deleteWebhook({ drop_pending_updates: true });

    // Start bot with long polling
    bot.start({
        onStart: (botInfo) => {
            console.log(`✅ @${botInfo.username} CONECTADO.`);
        }
    });

    // Graceful shutdown
    process.once('SIGINT', () => bot.stop());
    process.once('SIGTERM', () => bot.stop());
}

main().catch(console.error);
