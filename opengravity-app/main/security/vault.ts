import * as keytar from 'keytar';
import * as fs from 'fs';
import * as path from 'path';
import * as dotenv from 'dotenv';

const SERVICE_NAME = 'OpenGravity';
const PLACEHOLDERS = ['tu_clave_aqui', 'tu_client_id', 'tu_client_secret', ''];

export class Vault {
  /**
   * Set a secret in the OS vault.
   */
  static async set(key: string, value: string): Promise<void> {
    await keytar.setPassword(SERVICE_NAME, key, value);
  }

  /**
   * Get a secret from the OS vault.
   */
  static async get(key: string): Promise<string | null> {
    return await keytar.getPassword(SERVICE_NAME, key);
  }

  /**
   * Delete a secret from the OS vault.
   */
  static async delete(key: string): Promise<boolean> {
    return await keytar.deletePassword(SERVICE_NAME, key);
  }

  /**
   * Check if a secret exists in the vault.
   */
  static async exists(key: string): Promise<boolean> {
    const val = await this.get(key);
    return val !== null;
  }

  /**
   * Migrate secrets from a .env file to the vault.
   * Returns the number of keys migrated.
   */
  static async migrateFromEnv(envPath: string): Promise<number> {
    if (!fs.existsSync(envPath)) return 0;

    const envConfig = dotenv.parse(fs.readFileSync(envPath));
    let count = 0;

    for (const [key, value] of Object.entries(envConfig)) {
      if (value && !PLACEHOLDERS.includes(value.toLowerCase())) {
        await this.set(key, value);
        count++;
      }
    }

    return count;
  }
}
