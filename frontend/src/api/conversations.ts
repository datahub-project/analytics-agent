import type { ConversationDetail, ConversationSummary, Engine, ProposalItem } from "@/types";
import { streamMessage } from "@/api/stream";

const BASE = "/api";

export async function listConversations(): Promise<ConversationSummary[]> {
  const res = await fetch(`${BASE}/conversations`);
  if (!res.ok) throw new Error("Failed to fetch conversations");
  return res.json();
}

export async function createConversation(
  engine_name: string,
  title = "New Conversation"
): Promise<ConversationSummary> {
  const res = await fetch(`${BASE}/conversations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, engine_name }),
  });
  if (!res.ok) throw new Error("Failed to create conversation");
  return res.json();
}

export async function getConversation(id: string): Promise<ConversationDetail> {
  const res = await fetch(`${BASE}/conversations/${id}`);
  if (!res.ok) throw new Error("Failed to fetch conversation");
  return res.json();
}

export async function deleteConversation(id: string): Promise<void> {
  const res = await fetch(`${BASE}/conversations/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to delete conversation");
}

export async function generateTitle(
  id: string
): Promise<{ title: string; updated: boolean }> {
  const res = await fetch(`${BASE}/conversations/${id}/generate-title`, {
    method: "POST",
  });
  if (!res.ok) throw new Error("Title generation failed");
  return res.json();
}

export async function listEngines(): Promise<Engine[]> {
  const res = await fetch(`${BASE}/engines`);
  if (!res.ok) throw new Error("Failed to fetch engines");
  return res.json();
}

export interface ContextQuality {
  score: number;
  label: string;
  breakdown: Record<string, number>;
}

export async function getContextQuality(conversationId: string): Promise<ContextQuality> {
  const res = await fetch(`${BASE}/conversations/${conversationId}/quality`);
  if (!res.ok) throw new Error("Failed to fetch context quality");
  return res.json();
}

/**
 * Submit a proposal selection back to the agent as a user turn.
 * Returns the underlying SSE stream so callers can consume events.
 */
export function sendProposalSelection(
  conversationId: string,
  originMessageId: string,
  selectedIds: string[],
  proposals: ProposalItem[]
) {
  const selectedItems = proposals.filter((p) => selectedIds.includes(p.id));
  const agentText =
    selectedItems.length === 0
      ? "Skip all proposals — make no changes."
      : `Publish the following proposals: ${selectedItems.map((p) => `"${p.title}"`).join(", ")}.`;
  const displayText =
    selectedItems.length === 0
      ? "Skipped proposals"
      : `Selected ${selectedItems.length} proposal${selectedItems.length === 1 ? "" : "s"}`;

  return streamMessage(conversationId, agentText, undefined, {
    source: "proposal_select",
    origin_message_id: originMessageId,
    display_text: displayText,
    selected_ids: selectedIds,
  });
}
