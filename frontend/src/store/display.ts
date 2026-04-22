import { create } from "zustand";

interface DisplayState {
  appName: string;
  logoUrl: string;
  greeting: string;
  userName: string;
  greetingGeneratedAt: number;   // ms timestamp, 0 = never
  setDisplay: (appName: string, logoUrl: string) => void;
  setGreeting: (greeting: string, userName: string) => void;
}

const GREETING_TTL_MS = 60 * 60 * 1000; // 1 hour

export const useDisplayStore = create<DisplayState>((set) => ({
  appName: "Analytics Agent",
  logoUrl: "",
  greeting: "",
  userName: "",
  greetingGeneratedAt: 0,
  setDisplay: (appName, logoUrl) => set({ appName, logoUrl }),
  setGreeting: (greeting, userName) => set({ greeting, userName, greetingGeneratedAt: Date.now() }),
}));

export { GREETING_TTL_MS };
