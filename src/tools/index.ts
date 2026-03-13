export * from './time.js';
import { Registry } from '../memory/index.js';
import { getCurrentTimeTool, getCurrentTime } from './time.js';
import { searchSkillsTool, searchSkills, requestSkillInstallTool, requestSkillInstall, installSkillTool, installSkill } from './skills.js';

export const allTools = [
    getCurrentTimeTool,
    searchSkillsTool,
    requestSkillInstallTool,
    installSkillTool
];

export async function executeTool(name: string, args: any) {
    // 1. Static tools
    switch (name) {
        case 'get_current_time': return await getCurrentTime(args);
        case 'search_skills': return await searchSkills(args);
        case 'request_skill_install': return await requestSkillInstall(args);
        case 'install_skill': return await installSkill(args);
    }

    // 2. Dynamic tools from Registry
    const activeSkills = await Registry.getSkills();
    const dynamicSkill = activeSkills.find(s => s.tool_schema?.function?.name === name);

    if (dynamicSkill) {
        console.log(`Executing dynamic tool: ${name}`);

        // --- REAL DATA FETCHING FOR CRYPTO ---
        if (name === 'crypto_dynamic') {
            try {
                const symbolMap: Record<string, string> = {
                    'btc': 'bitcoin',
                    'eth': 'ethereum',
                    'sol': 'solana',
                    'ada': 'cardano',
                    'dot': 'polkadot',
                    'doge': 'dogecoin'
                };
                const symbol = args.symbol?.toLowerCase() || 'btc';
                const geckoId = symbolMap[symbol] || symbol;

                const response = await fetch(`https://api.coingecko.com/api/v3/simple/price?ids=${geckoId}&vs_currencies=usd`);
                const data = await response.json();
                
                if (data[geckoId]) {
                    const price = data[geckoId].usd;
                    return `PRECIO REAL: El valor actual de ${symbol.toUpperCase()} es $${price} USD (vía CoinGecko).`;
                }
            } catch (e) {
                console.error("Error fetching real crypto data:", e);
                // Fallback to simulation if API fails
            }
        }

        // For now, we return the simulation prompt for other skills
        return `[SISTEMA]: Skill "${dynamicSkill.name}" activada.\nLógica: ${dynamicSkill.prompt_definition}\nArgumentos: ${JSON.stringify(args)}`;
    }

    throw new Error(`Tool ${name} not found`);
}

