import { chatCompletion } from './llm.js';
import { Memory, Registry } from '../memory/index.js';
import { executeTool } from '../tools/index.js';

const MAX_ITERATIONS = 3;

const MASTER_SYSTEM_PROMPT = `Eres OpenGravity, un Agente de IA personal y profesional.
TU REGLA DE ORO: NO INVENTES DATOS. 
- Si el usuario pide precios, clima o traducciones, USA LA HERRAMIENTA CORRESPONDIENTE.
- Si no usas la herramienta, tu respuesta no tiene valor. 
- NUNCA digas que estás "simulando" datos.
- Responde siempre con la información que te devuelva la herramienta.`;

export async function agentLoop(userMessage: string): Promise<string> {
    // Save user message to memory
    await Memory.addMessage({ role: 'user', content: userMessage });

    let iterations = 0;
    while (iterations < MAX_ITERATIONS) {
        iterations++;
        
        // Fetch context and Dynamic Skills
        let rawMessages = await Memory.getMessages();
        const activeSkills = await Registry.getSkills();

        // 1. Build fresh context
        const messages = [
            { role: 'system', content: MASTER_SYSTEM_PROMPT },
            ...rawMessages.filter(m => m.role !== 'system')
        ];

        // 2. Prepare dynamic tools for LLM
        const dynamicTools = activeSkills
            .filter(s => s.tool_schema)
            .map(s => s.tool_schema);

        // 3. Inform the agent about available modules (without giving it logic to simulate)
        if (activeSkills.length > 0) {
            const list = activeSkills.map(s => `- ${s.name}`).join('\n');
            messages[0].content += `\n\n[MÓDULOS ACTIVOS]\nCuentas con acceso real a estos sistemas:\n${list}\n\nRECUERDA: Llama a la función específica para obtener datos actualizados.`;
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
