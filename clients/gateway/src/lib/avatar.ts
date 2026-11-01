// A name's colour and letters: the avatar every thread has, the same one on every device.

/** Which of the eight palettes a thread's avatar takes; the same id always gets the same one. */
export function hueOf(id: string): number {
  let value = 0;
  for (const char of id) value = (value * 31 + (char.codePointAt(0) ?? 0)) >>> 0;
  return value % 8;
}

/** The two ends of each palette's gradient, in the order `hueOf` numbers them: the same colours as the avatars' CSS. */
export const PALETTE: readonly (readonly [string, string])[] = [
  ["#ff885e", "#ff516a"],
  ["#ffcd6a", "#ffa85c"],
  ["#82b1ff", "#665fff"],
  ["#a0de7e", "#54cb68"],
  ["#53edd6", "#28c9b7"],
  ["#72d5fd", "#2a9ef1"],
  ["#e0a2f3", "#d669ed"],
  ["#f7a3b6", "#ec5f87"],
];

/** The one or two letters on an avatar. */
export function initialsOf(name: string): string {
  const words = name.trim().split(/[\s_-]+/).filter(Boolean);
  const first = words[0] ?? "?";
  const letters = words.length > 1 ? [...first][0]! + [...words[1]!][0]! : [...first].slice(0, 2).join("");
  return letters.toUpperCase();
}
