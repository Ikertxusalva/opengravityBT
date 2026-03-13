import { Groq } from 'groq-sdk';
import OpenAI from 'openai';
import { ENV } from '../config/index.js';
import { allTools } from '../tools/index.js';

const groq = new Groq({ apiKey: ENV.GROQ_API_KEY });
let openrouter: OpenAI | null = null;

if (ENV.OPENROUTER_API_KEY) {
    openrouter = new OpenAI({
        baseURL: 'https://openrouter.ai/api/v1',
        apiKey: ENV.OPENROUTER_API_KEY,
    });
}

// Use 'llama-3.1-8b-instant' for extremely fast responses
// Recommended for chat and simple tool usage
// Switching to llama-3.1-8b-instant to dodge the tight TPD (Tokens Per Day) limits of the 70b model
export const MAIN_MODEL = 'llama-3.1-8b-instant';
export const ADVANCED_MODEL = 'llama-3.3-70b-versatile';

export async function chatCompletion(messages: any[], dynamicTools: any[] = []) {
    try {
        const combinedTools = [...allTools, ...dynamicTools];
        
        // Try Groq first
        const response = await groq.chat.completions.create({
            model: MAIN_MODEL,
            messages: messages,
            tools: combinedTools.length > 0 ? combinedTools : undefined,
            tool_choice: combinedTools.length > 0 ? 'auto' : undefined
        });
        
        return response.choices[0].message;
    } catch (e: any) {
        console.error("Groq API error:", e.message);
        
        // Fallback to openrouter
        if (openrouter) {
            console.log(`Falling back to OpenRouter using model ${ENV.OPENROUTER_MODEL}...`);
            try {
                const response = await openrouter.chat.completions.create({
                    model: ENV.OPENROUTER_MODEL,
                    messages: messages as any,
                    tools: allTools as any,
                    tool_choice: 'auto'
                });
                return response.choices[0].message;
            } catch (fbError: any) {
                console.error("OpenRouter fallback error:", fbError.message);
                throw new Error("Both Groq and fallback providers failed.");
            }
        }
        
        throw new Error(`Groq failed and no fallback available: ${e.message}`);
    }
}
