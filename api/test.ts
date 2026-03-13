export default function handler(req: any, res: any) {
    try {
        res.json({
            ok: true,
            hasTelegramToken: !!process.env.TELEGRAM_BOT_TOKEN,
            hasAllowedUsers: !!process.env.TELEGRAM_ALLOWED_USER_IDS,
            hasGroqKey: !!process.env.GROQ_API_KEY,
            hasGoogleCreds: !!process.env.GOOGLE_APPLICATION_CREDENTIALS,
            credStart: process.env.GOOGLE_APPLICATION_CREDENTIALS ? process.env.GOOGLE_APPLICATION_CREDENTIALS.substring(0, 15) : null,
            envKeys: Object.keys(process.env).filter(k => k.includes('TELEGRAM') || k.includes('GROQ') || k.includes('GOOGLE'))
        });
    } catch (e: any) {
        res.status(500).json({ error: e.message });
    }
}
