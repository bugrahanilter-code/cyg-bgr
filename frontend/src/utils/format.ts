/** Formatting helpers used across the dashboard. */

const CURRENCY_FORMATTER = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/**
 * The backend stores naive UTC timestamps. Without an explicit timezone the
 * browser would interpret them as local time, so we append the Z here in one
 * central place.
 */
export function parseUtc(value: string | null | undefined): Date | null {
  if (!value) {
    return null;
  }
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value);
  const parsed = new Date(hasZone ? value : value + "Z");
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function formatDateTime(value: string | null | undefined): string {
  const parsed = parseUtc(value);
  if (!parsed) {
    return "-";
  }
  return parsed.toLocaleString(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatTime(value: string | null | undefined): string {
  const parsed = parseUtc(value);
  return parsed ? parsed.toLocaleTimeString() : "-";
}

export function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatCurrency(value: number | null | undefined, symbol = "$"): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  const sign = value < 0 ? "-" : "";
  return sign + symbol + CURRENCY_FORMATTER.format(Math.abs(value));
}

export function formatSignedCurrency(value: number | null | undefined, symbol = "$"): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  const prefix = value > 0 ? "+" : value < 0 ? "-" : "";
  return prefix + symbol + CURRENCY_FORMATTER.format(Math.abs(value));
}

export function formatPercent(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  const prefix = value > 0 ? "+" : "";
  return prefix + value.toFixed(digits) + "%";
}

export function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  const digits = value >= 1000 ? 2 : value >= 1 ? 4 : 6;
  return value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatQuantity(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return value.toFixed(6).replace(/0+$/, "").replace(/\.$/, "");
}

export function formatDuration(seconds: number | null | undefined): string {
  if (!seconds || seconds <= 0) {
    return "-";
  }
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) {
    return days + "d " + hours + "h";
  }
  if (hours > 0) {
    return hours + "h " + minutes + "m";
  }
  return minutes + "m";
}

export function formatAgo(value: string | null | undefined): string {
  const parsed = parseUtc(value);
  if (!parsed) {
    return "never";
  }
  const seconds = Math.max(0, (Date.now() - parsed.getTime()) / 1000);
  if (seconds < 60) {
    return Math.round(seconds) + "s ago";
  }
  if (seconds < 3600) {
    return Math.round(seconds / 60) + "m ago";
  }
  return Math.round(seconds / 3600) + "h ago";
}

export function pnlClass(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) {
    return "neutral";
  }
  return value > 0 ? "positive" : "negative";
}

export function titleCase(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

export function toIsoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

export function daysAgoIso(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return toIsoDate(date);
}
