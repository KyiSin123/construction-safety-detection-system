import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

function browserStorage(): Storage | null {
  return typeof window === 'undefined' ? null : window.localStorage;
}

export const tokenStorage = {
  async getItemAsync(key: string): Promise<string | null> {
    if (Platform.OS === 'web') return browserStorage()?.getItem(key) ?? null;
    return SecureStore.getItemAsync(key);
  },

  async setItemAsync(key: string, value: string): Promise<void> {
    if (Platform.OS === 'web') {
      browserStorage()?.setItem(key, value);
      return;
    }
    await SecureStore.setItemAsync(key, value);
  },

  async deleteItemAsync(key: string): Promise<void> {
    if (Platform.OS === 'web') {
      browserStorage()?.removeItem(key);
      return;
    }
    await SecureStore.deleteItemAsync(key);
  },
};
