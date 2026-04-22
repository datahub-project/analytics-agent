import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { ThemeId } from "@/components/Brand/ThemeSwitcher";

interface ThemeState {
  theme: ThemeId;
  setTheme: (t: ThemeId) => void;
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      theme: "datahub",
      setTheme: (theme) => {
        document.documentElement.setAttribute("data-theme", theme);
        document.documentElement.classList.toggle(
          "theme-dark",
          theme === "carbon" || theme === "ocean"
        );
        set({ theme });
      },
    }),
    {
      name: "analytics-agent-theme",
      onRehydrateStorage: () => (state) => {
        if (state?.theme) {
          document.documentElement.setAttribute("data-theme", state.theme);
        }
      },
    }
  )
);
