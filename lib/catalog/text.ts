export function compactOfficialText(value: string): string {
  return value
    .replace(/\r\n?/g, "\n")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n[ \t]*\n+/g, "\n")
    .trim();
}
