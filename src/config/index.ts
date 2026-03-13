import { config } from 'dotenv';
import { resolve } from 'path';

// Load environment variables from .env file
config({ path: resolve(process.cwd(), '.env') });

function requireEnv(name: string): string {
    const value = process.env[name];
    if (!value) {
        throw new Error(`Missing required environment variable: ${name}`);
    }
    return value;
}

export const ENV = {
    TELEGRAM_BOT_TOKEN: requireEnv('TELEGRAM_BOT_TOKEN'),
    // Parse comma-separated list of allowed user IDs
    TELEGRAM_ALLOWED_USER_IDS: requireEnv('TELEGRAM_ALLOWED_USER_IDS')
        .split(',')
        .map((id) => parseInt(id.trim(), 10))
        .filter((id) => !isNaN(id)),
    GROQ_API_KEY: requireEnv('GROQ_API_KEY'),
    OPENROUTER_API_KEY: process.env.OPENROUTER_API_KEY || '',
    OPENROUTER_MODEL: process.env.OPENROUTER_MODEL || 'openrouter/free',
    DB_PATH: process.env.DB_PATH || './memory.db',
    GOOGLE_APPLICATION_CREDENTIALS: process.env.GOOGLE_APPLICATION_CREDENTIALS || './service-account.json',
};

// Validate some basics
if (ENV.TELEGRAM_ALLOWED_USER_IDS.length === 0) {
    console.warn("WARNING: No allowed Telegram user IDs configured. The bot won't respond to anyone.");
}
