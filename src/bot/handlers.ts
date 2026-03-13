import { Context } from 'grammy';
import { agentLoop } from '../agent/loop.js';

export async function handleMessage(ctx: Context) {
    if (!ctx.message || !ctx.message.text) return;

    const userId = ctx.from?.id;
    if (!userId) return;

    const text = ctx.message.text;

    try {
        // Show typing action in Telegram
        await ctx.replyWithChatAction('typing');

        // Pass message to Agent Loop
        const reply = await agentLoop(text);

        // Send response back
        await ctx.reply(reply);
    } catch (error: any) {
        console.error("Error handling message:", error);
        await ctx.reply("Ha ocurrido un error procesando tu mensaje. Revisa los logs.");
    }
}
