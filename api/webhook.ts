import { webhookCallback } from 'grammy';
import { bot } from '../src/bot/index.js';

export default async function handler(req: any, res: any) {
    try {
        console.log("📥 Recibiendo payload en webhook...");
        const callback = webhookCallback(bot, 'http');
        await callback(req, res);
    } catch (e: any) {
        console.error("❌ Error en webhook:", e);
        res.statusCode = 500;
        res.end(e.message);
    }
}
