import { chatCompletion } from './llm.js';
import { Memory, Registry } from '../memory/index.js';
import { executeTool } from '../tools/index.js';

const MAX_ITERATIONS = 3;

const MASTER_SYSTEM_PROMPT = `Eres OpenGravity, un Agente de IA personal, privado y EXTENSIBLE.
TU MISIÓN: Ejecutar las peticiones del usuario de forma DIRECTA.
- Si el usuario pide algo que requiere una herramienta (Tool), LLÁMALA EN TU PRIMERA RESPUESTA. No preguntes si quieres usarla, úsala.
- Si no tienes la herramienta, usa 'search_skills'.
- No menciones comandos técnicos (npx, tsx, etc.) al usuario.
- Sé breve y eficiente.`;

export async function agentLoop(userMessage: string): Promise<string> {
    // Save user message to memory
    await Memory.addMessage({ role: 'user', content: userMessage });

    let iterations = 0;
    while (iterations < MAX_ITERATIONS) {
        iterations++;
        
        // Fetch context and Dynamic Skills
        let rawMessages = await Memory.getMessages();
        const activeSkills = await Registry.getSkills();

        // 1. Build fresh context: Filter out old system messages and start with Master Prompt
        const messages = [
            { role: 'system', content: MASTER_SYSTEM_PROMPT },
            ...rawMessages.filter(m => m.role !== 'system')
        ];

        // 2. Prepare dynamic tools for LLM
        const dynamicTools = activeSkills
            .filter(s => s.tool_schema)
            .map(s => s.tool_schema);

        // 3. Inject active skills info into the Master Prompt (first message)
        if (activeSkills.length > 0) {
            const skillsInstructions = activeSkills
                .filter(s => s.prompt_definition)
                .map(s => `- ${s.name}: ${s.prompt_definition}`)
                .join('\n');
            messages[0].content += `\n\n[CAPACIDADES INSTALADAS]\nActualmente tienes activas estas funciones:\n${skillsInstructions}`;
        }

        // Call LLM with static + dynamic tools
        const response = await chatCompletion(messages, dynamicTools);

        // Analyze response
        const { role, content, tool_calls } = response;

        // Save assistant response to memory
        await Memory.addMessage({
            role: role as 'assistant',
            content: content || '',
            tool_calls: tool_calls
        });

        if (tool_calls && tool_calls.length > 0) {
            for (const call of tool_calls) {
                const toolCall = call as any; // Cast to bypass overly strict Groq SDK types
                console.log(`Executing tool: ${toolCall.function.name}`);
                const args = JSON.parse(toolCall.function.arguments);
                
                try {
                    const result = await executeTool(toolCall.function.name, args);
                    // Save tool result
                    await Memory.addMessage({
                        role: 'tool',
                        content: String(result),
                        name: toolCall.function.name,
                        tool_call_id: toolCall.id
                    });
                } catch (e: any) {
                    await Memory.addMessage({
                        role: 'tool',
                        content: `Error executing tool: ${e.message}`,
                        name: toolCall.function.name,
                        tool_call_id: toolCall.id
                    });
                }
            }
            // Loop continues after tools
        } else {
            // No tools called, final response
            return content || '';
        }
    }

    return "Lo siento, he excedido el número máximo de iteraciones para esta tarea.";
}
