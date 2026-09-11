/** Earliest due check for a newly created subscription; actual dispatch is polled by the service. */
export function firstSubscriptionCheck(
  cadence: string,
  time: string,
  day: string,
  now = new Date(),
): Date | null {
  if (cadence === "每小时" || cadence === "hourly") return now;
  const match = /^([01]\d|2[0-3]):([0-5]\d)$/.exec(time);
  if (!match) return null;
  const next = new Date(now);
  next.setHours(Number(match[1]), Number(match[2]), 0, 0);
  if (cadence === "每周") {
    const target = Number(day);
    if (!Number.isInteger(target) || target < 1 || target > 7) return null;
    const offset = (target - (now.getDay() || 7) + 7) % 7;
    next.setDate(next.getDate() + offset);
  }
  // The backend runs a fresh subscription immediately once its scheduled time has passed.
  return next < now ? now : next;
}
