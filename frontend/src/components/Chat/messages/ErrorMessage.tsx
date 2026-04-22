import { AlertCircle } from "lucide-react";

interface Props {
  payload: { error: string };
}

export function ErrorMessage({ payload }: Props) {
  return (
    <div className="max-w-[90%] flex items-start gap-2 px-3 py-2 rounded-lg border border-red-200 bg-red-50 text-red-700 text-xs">
      <AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
      <span className="font-mono leading-relaxed">{payload.error}</span>
    </div>
  );
}
