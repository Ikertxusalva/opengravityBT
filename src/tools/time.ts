export const getCurrentTimeTool = {
    type: 'function',
    function: {
        name: 'get_current_time',
        description: 'Gets the current local time of the user',
        parameters: {
            type: 'object',
            properties: {
                timezone: {
                    type: 'string',
                    description: 'Optional timezone (e.g., "Europe/Madrid"). Defaults to local time if not provided.'
                }
            },
            required: []
        }
    }
};

export async function getCurrentTime(args: any) {
    try {
        const date = new Date();
        if (args.timezone) {
            return new Intl.DateTimeFormat('es-ES', {
                dateStyle: 'full',
                timeStyle: 'long',
                timeZone: args.timezone
            }).format(date);
        }
        return date.toString();
    } catch (e: any) {
        return `Error getting time: ${e.message}`;
    }
}
