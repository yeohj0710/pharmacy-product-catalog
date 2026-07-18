export function compactOfficialText(value: string): string {
  return value
    .replace(/\r\n?/g, "\n")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n[ \t]*\n+/g, "\n")
    .trim();
}

const consumerGuidanceFields = [
  ["summary", "무슨 약인가요"],
  ["efficacy", "효능·효과"],
  ["guide", "어떻게 복용하나요"],
  ["dosage", "복용 방법"],
  ["warning", "복용 전 경고"],
  ["precautions", "주의사항"],
  ["interactions", "상호작용"],
  ["side_effects", "부작용"],
  ["storage", "보관 방법"],
] as const;

export function formatConsumerGuidance(value: unknown): string {
  if (!value || typeof value !== "object" || Array.isArray(value)) return "";
  const guidance = value as Record<string, unknown>;
  return consumerGuidanceFields
    .map(([key, label]) => {
      const text = guidance[key];
      return typeof text === "string" && text.trim()
        ? `${label}\n${compactOfficialText(text)}`
        : "";
    })
    .filter(Boolean)
    .join("\n\n");
}

export function dedupeLabeledText(items: Array<[string, string]>): Array<[string, string]> {
  const kept: Array<[string, string]> = [];
  const rendered: string[] = [];
  for (const [label, value] of items) {
    const text = compactOfficialText(value);
    if (!text) continue;
    const comparable = text.replace(/\s+/g, " ").trim();
    if (rendered.some((existing) => existing === comparable || existing.includes(comparable))) continue;
    kept.push([label, text]);
    rendered.push(comparable);
  }
  return kept;
}
