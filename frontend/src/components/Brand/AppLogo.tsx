import { useDisplayStore } from "@/store/display";

export function AppLogo() {
  const { appName, logoUrl } = useDisplayStore();

  return (
    <div className="flex items-center gap-2 select-none">
      {logoUrl ? (
        <img
          src={logoUrl}
          alt="Logo"
          className="w-5 h-5 object-contain flex-shrink-0"
          onError={(e) => ((e.target as HTMLImageElement).style.display = "none")}
        />
      ) : (
        <svg width="22" height="22" viewBox="0 0 64 64" fill="none" aria-hidden>
          <path d="M8 42 A30 30 0 0 1 52 10" stroke="#0078D4" strokeWidth="7" strokeLinecap="round"/>
          <path d="M56 42 A30 30 0 0 0 12 10" stroke="#E8A030" strokeWidth="7" strokeLinecap="round"/>
          <circle cx="24" cy="28" r="3.5" fill="#D44B20"/>
          <circle cx="32" cy="28" r="3.5" fill="#D44B20"/>
          <circle cx="40" cy="28" r="3.5" fill="#D44B20"/>
          <path d="M8 42 L3 54 L17 45" stroke="#0078D4" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round"/>
          <path d="M56 42 L61 54 L47 45" stroke="#E8A030" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      )}
      <span
        className="text-base font-semibold tracking-tight text-foreground"
        style={{ letterSpacing: "-0.02em" }}
      >
        {appName || "Analytics Agent"}
      </span>
    </div>
  );
}
