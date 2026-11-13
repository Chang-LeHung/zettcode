/** The day a conversation divider names, as a messenger writes it: today, yesterday, the weekday for the past week, else the date. */
export type DayName = { kind: "today" } | { kind: "yesterday" } | { kind: "weekday"; text: string } | { kind: "date"; text: string };

const startOfDay = (ms: number): number => {
  const d = new Date(ms);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
};

/** Whether two instants (milliseconds) fall on the same calendar day in the reader's time zone. */
export function sameDay(a: number, b: number): boolean {
  return startOfDay(a) === startOfDay(b);
}

/** Name the day of `ms` as seen on `now`. `locale` is the reader's; the calendar words ("Today") are the caller's to translate. */
export function dayName(ms: number, now: number, locale?: string): DayName {
  const days = Math.round((startOfDay(now) - startOfDay(ms)) / 86_400_000);
  if (days === 0) return { kind: "today" };
  if (days === 1) return { kind: "yesterday" };
  const when = new Date(ms);
  if (days > 1 && days < 7) return { kind: "weekday", text: when.toLocaleDateString(locale, { weekday: "long" }) };
  const sameYear = when.getFullYear() === new Date(now).getFullYear();
  return {
    kind: "date",
    text: when.toLocaleDateString(locale, sameYear ? { month: "short", day: "numeric" } : { year: "numeric", month: "short", day: "numeric" }),
  };
}
