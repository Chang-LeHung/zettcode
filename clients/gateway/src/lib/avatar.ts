// A name's colour and letters: the avatar every thread has, the same one on every device.

/** Which of the eight palettes a thread's avatar takes; the same id always gets the same one. */
export function hueOf(id: string): number {
  let value = 0;
  for (const char of id) value = (value * 31 + (char.codePointAt(0) ?? 0)) >>> 0;
  return value % 8;
}

/** The one or two letters on an avatar. */
export function initialsOf(name: string): string {
  const words = name.trim().split(/[\s_-]+/).filter(Boolean);
  const first = words[0] ?? "?";
  const letters = words.length > 1 ? [...first][0]! + [...words[1]!][0]! : [...first].slice(0, 2).join("");
  return letters.toUpperCase();
}
