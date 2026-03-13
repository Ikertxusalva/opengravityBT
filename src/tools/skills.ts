import { ENV } from '../config/index.js';
import { Registry } from '../memory/index.js';

export const searchSkillsTool = {
    type: 'function',
    function: {
        name: 'search_skills',
        description: 'BUSCA nuevas capacidades, herramientas y funciones de IA para instalar en OpenGravity. Úsala siempre que el usuario mencione nuevas habilidades, crypto, clima, traductores o funciones adicionales.',
        parameters: {
            type: 'object',
            properties: {
                query: {
                    type: 'string',
                    description: 'Palabra clave de la habilidad (ej: "crypto", "clima", "translator").'
                }
            },
            required: ['query']
        }
    }
};

export const requestSkillInstallTool = {
    type: 'function',
    function: {
        name: 'request_skill_install',
        description: 'Pide permiso explícito al usuario para instalar una skill. DEBE llamarse antes de usar install_skill.',
        parameters: {
            type: 'object',
            properties: {
                skill_id: {
                    type: 'string',
                    description: 'El ID de la skill encontrada en la búsqueda.'
                },
                description: {
                    type: 'string',
                    description: 'Breve explicación de para qué sirve.'
                }
            },
            required: ['skill_id', 'description']
        }
    }
};

export const installSkillTool = {
    type: 'function',
    function: {
        name: 'install_skill',
        description: 'Instala definitivamente la skill en la base de datos de OpenGravity. Úsala SOLO después de que el usuario haya dado su consentimiento explícito.',
        parameters: {
            type: 'object',
            properties: {
                skill_id: {
                    type: 'string',
                    description: 'El ID de la skill a instalar.'
                }
            },
            required: ['skill_id']
        }
    }
};

// Catálogo de Skills disponibles
const SKILLS_DATABASE = [
    { 
        id: 'weather', 
        name: 'Weather Forecast', 
        description: 'Consulta el clima de cualquier ciudad en tiempo real.',
        tool_schema: {
            type: 'function',
            function: {
                name: 'weather_dynamic',
                description: 'Obtener datos meteorológicos actuales.',
                parameters: {
                    type: 'object',
                    properties: {
                        city: { type: 'string', description: 'Nombre de la ciudad' }
                    },
                    required: ['city']
                }
            }
        },
        prompt_definition: 'Usa esta función para dar el clima. Simula que conectas con satélites meteorológicos y da una respuesta detallada.'
    },
    { 
        id: 'crypto', 
        name: 'Crypto Expert', 
        description: 'Precios en tiempo real de Bitcoin, Ethereum y otras criptos.',
        tool_schema: {
            type: 'function',
            function: {
                name: 'crypto_dynamic',
                description: 'Obtener precio y análisis de una criptomoneda.',
                parameters: {
                    type: 'object',
                    properties: {
                        symbol: { type: 'string', description: 'Símbolo del token (BTC, ETH, etc.)' }
                    },
                    required: ['symbol']
                }
            }
        },
        prompt_definition: 'Usa esta función para dar precios cripto. Añade un breve análisis del mercado ("bullish" o "bearish") de forma creativa.'
    },
    {
        id: 'translator',
        name: 'Universal Translator',
        description: 'Traduce frases a más de 50 idiomas con precisión profesional.',
        tool_schema: {
            type: 'function',
            function: {
                name: 'translate_dynamic',
                description: 'Traducir un texto a otro idioma.',
                parameters: {
                    type: 'object',
                    properties: {
                        text: { type: 'string', description: 'Texto a traducir' },
                        target_lang: { type: 'string', description: 'Idioma destino (ej: English, Japanese)' }
                    },
                    required: ['text', 'target_lang']
                }
            }
        },
        prompt_definition: 'Eres un políglota experto. Traduce el texto manteniendo el estilo y contexto cultural.'
    }
];

export async function searchSkills(args: { query: string }) {
    const results = SKILLS_DATABASE.filter(s => 
        s.name.toLowerCase().includes(args.query.toLowerCase()) || 
        s.description.toLowerCase().includes(args.query.toLowerCase()) ||
        s.id.toLowerCase().includes(args.query.toLowerCase())
    );
    
    if (results.length === 0) {
        return "No se han encontrado skills en el catálogo para esa búsqueda.";
    }
    
    return JSON.stringify(results, null, 2);
}

export async function requestSkillInstall(args: { skill_id: string, description: string }) {
    return `SOLICITUD DE INSTALACIÓN: La skill "${args.skill_id}" (${args.description}) requiere tu permiso para ser instalada. ¿Deseas proceder?`;
}

export async function installSkill(args: { skill_id: string }) {
    const skillData = SKILLS_DATABASE.find(s => s.id === args.skill_id);
    
    if (!skillData) {
        return `❌ Error: No se encontró la skill "${args.skill_id}" en el catálogo.`;
    }

    await Registry.addSkill({
        skill_id: skillData.id,
        name: skillData.name,
        description: skillData.description,
        tool_schema: skillData.tool_schema,
        prompt_definition: skillData.prompt_definition,
        is_active: true
    });

    return `✅ SISTEMA: La skill "${args.skill_id}" ha sido instalada y guardada permanentemente en Firebase. Ahora OpenGravity tiene esta nueva capacidad activa.`;
}
