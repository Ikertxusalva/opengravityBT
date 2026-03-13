import { initializeApp, cert } from 'firebase-admin/app';
import { getFirestore, Timestamp } from 'firebase-admin/firestore';
import { ENV } from '../config/index.js';

// Initialize Firebase App
let db: FirebaseFirestore.Firestore;
try {
    const credPathOrString = ENV.GOOGLE_APPLICATION_CREDENTIALS;
    
    // Check if it's a JSON string (for Cloud deployment) or a file path (for local)
    let credentialInput: any;
    
    // Automatically add curly braces if the user missed them while copying
    let possibleJson = credPathOrString.trim();
    if (possibleJson.includes('"type"') && possibleJson.includes('"project_id"')) {
        if (!possibleJson.startsWith('{')) possibleJson = '{' + possibleJson;
        if (!possibleJson.endsWith('}')) possibleJson = possibleJson + '}';
        
        credentialInput = JSON.parse(possibleJson);
        // Ensure private key string newlines from Vercel ENV are formatted properly
        if (credentialInput.private_key) {
            credentialInput.private_key = credentialInput.private_key.replace(/\\n/g, '\n');
        }
    } else {
        credentialInput = credPathOrString;
    }

    initializeApp({
        credential: cert(credentialInput)
    });
    db = getFirestore();
    console.log("✅ Conectado a Firebase Firestore");
} catch (error) {
    console.error("❌ Error inicializando Firebase:", error);
    // process.exit(1); -> Removed to prevent Vercel Serverless crashes
}

export interface MessageRow {
    role: 'user' | 'assistant' | 'system' | 'tool';
    content: string;
    name?: string | null;
    tool_call_id?: string | null;
    tool_calls?: any[] | null;
    created_at: number;
}

export interface SkillRow {
    id?: string;
    skill_id: string;
    name: string;
    description: string;
    api_url?: string;
    prompt_definition?: string;
    tool_schema?: any; // JSON schema for LLM tool calling
    is_active: boolean;
    created_at: number;
}

// Ensure the system message exists
async function ensureSystemMessage() {
    if (!db) return;
    try {
        const snap = await db.collection('messages').where('role', '==', 'system').limit(1).get();
        if (snap.empty) {
            await Memory.addMessage({
                role: 'system',
                content: "Eres OpenGravity, un Agente de IA personal, privado y EXTENSIBLE. Tienes la capacidad de BUSCAR E INSTALAR nuevas 'Skills' (habilidades de IA) para ampliar tus funciones. Cuando el usuario te pregunte por habilidades o nuevas funciones, utiliza siempre la herramienta 'search_skills' para ver qué hay disponible en tu catálogo."
            });
        }
    } catch (e: any) {
        console.error("Error ensureSystemMessage:", e.message);
    }
}
ensureSystemMessage();

export const Memory = {
    addMessage: async (msg: {
        role: 'user' | 'assistant' | 'system' | 'tool';
        content: string;
        name?: string;
        tool_call_id?: string;
        tool_calls?: any[];
    }) => {
        try {
            const newMsg: MessageRow = {
                role: msg.role,
                content: msg.content,
                created_at: Date.now()
            };
            if (msg.name) newMsg.name = msg.name;
            if (msg.tool_call_id) newMsg.tool_call_id = msg.tool_call_id;
            if (msg.tool_calls) newMsg.tool_calls = msg.tool_calls;

            await db.collection('messages').add(newMsg);
        } catch (error) {
            console.error("Error saving message to Firebase:", error);
        }
    },

    getMessages: async (limit: number = 50): Promise<any[]> => {
        try {
            const snap = await db.collection('messages')
                .orderBy('created_at', 'desc')
                .limit(limit)
                .get();
                
            const rows: MessageRow[] = [];
            snap.forEach(doc => {
                rows.push(doc.data() as MessageRow);
            });

            // Revert back so oldest is first within the N limit
            return rows.reverse().map(row => {
                const docObj: any = {
                    role: row.role,
                    content: row.content,
                };
                if (row.name) docObj.name = row.name;
                if (row.tool_call_id) docObj.tool_call_id = row.tool_call_id;
                if (row.tool_calls) docObj.tool_calls = row.tool_calls;
                return docObj;
            });
        } catch (error) {
            console.error("Error fetching messages from Firebase:", error);
            return [];
        }
    },

    clearMemory: async () => {
        try {
            const snap = await db.collection('messages').get();
            const batch = db.batch();
            snap.docs.forEach((doc) => {
                batch.delete(doc.ref);
            });
            await batch.commit();
        } catch (error) {
            console.error("Error clearing Firebase memory:", error);
        }
    }
};

// Simple in-memory cache for skills
let skillsCache: SkillRow[] | null = null;
let lastCacheUpdate = 0;
const CACHE_TTL = 30000; // 30 seconds

export const Registry = {
    addSkill: async (skill: Omit<SkillRow, 'created_at'>) => {
        try {
            const newSkill: SkillRow = {
                ...skill,
                created_at: Date.now(),
                is_active: true
            };
            await db.collection('skills').doc(skill.skill_id).set(newSkill);
            // Invalidate cache
            skillsCache = null;
        } catch (error) {
            console.error("Error adding skill to Firebase:", error);
        }
    },

    getSkills: async (): Promise<SkillRow[]> => {
        try {
            // Return from cache if still valid
            if (skillsCache && (Date.now() - lastCacheUpdate < CACHE_TTL)) {
                return skillsCache;
            }

            const snap = await db.collection('skills')
                .where('is_active', '==', true)
                .get();
                
            const skills: SkillRow[] = [];
            snap.forEach(doc => {
                skills.push(doc.data() as SkillRow);
            });

            // Update cache
            skillsCache = skills;
            lastCacheUpdate = Date.now();
            
            return skills;
        } catch (error) {
            console.error("Error fetching skills from Firebase:", error);
            return [];
        }
    },

    removeSkill: async (skill_id: string) => {
        try {
            await db.collection('skills').doc(skill_id).update({ is_active: false });
            // Invalidate cache
            skillsCache = null;
        } catch (error) {
            console.error("Error removing skill from Firebase:", error);
        }
    }
};
