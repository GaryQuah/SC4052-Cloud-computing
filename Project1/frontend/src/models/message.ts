export type Message = { type: "user" | "bot"; text: string };
export type HistoryMessage = { role: "user" | "assistant"; content: string };
