import { useThemeStore } from "@/store/theme";

const THEMES = [
  { id: "datahub",  label: "DataHub",  swatch: "#533FD1" },
  { id: "warm",     label: "Warm",     swatch: "#da7e09" },
  { id: "ocean",    label: "Ocean",    swatch: "#58a6ff" },
  { id: "carbon",   label: "Carbon",   swatch: "#9a9aa0" },
] as const;

export type ThemeId = typeof THEMES[number]["id"];

export function ThemeSwitcher() {
  const { theme, setTheme } = useThemeStore();

  return (
    <div className="flex items-center gap-1">
      {THEMES.map((t) => (
        <div key={t.id} className="relative group">
          {/* Tooltip */}
          <span className="
            pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5
            px-1.5 py-0.5 rounded text-[10px] font-medium whitespace-nowrap
            bg-foreground text-background opacity-0 group-hover:opacity-100
            transition-opacity duration-150
          ">
            {t.label}
          </span>
          <button
            onClick={() => setTheme(t.id)}
            aria-label={t.label}
            className={`w-4 h-4 rounded-full border-2 transition-all ${
              theme === t.id
                ? "border-foreground/60 scale-110"
                : "border-transparent opacity-50 hover:opacity-80"
            }`}
            style={{ backgroundColor: t.swatch }}
          />
        </div>
      ))}
    </div>
  );
}
