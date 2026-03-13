import { Bot, Context, NextFunction } from 'grammy';
import { ENV } from '../config/index.js';
import { handleMessage } from './handlers.js';

export const bot = new Bot(ENV.TELEGRAM_BOT_TOKEN);

// Middleware to check whitelist
bot.use(async (ctx: Context, next: NextFunction) => {
    const userId = ctx.from?.id;
    if (!userId || !ENV.TELEGRAM_ALLOWED_USER_IDS.includes(userId)) {
        console.log(`Unauthorized access attempt from user ID: ${userId}`);
        // We do not even reply to unauthorized users for security
        return;
    }
    await next();
});

// Basic commands
bot.command('start', async (ctx) => {
    await ctx.reply("👋 Hola, soy OpenGravity. Estoy listo para ayudarte.");
});

// Message handler
bot.on('message:text', handleMessage);

// Error handler
bot.catch((err) => {
    console.error(`Error in bot:`, err);
});
