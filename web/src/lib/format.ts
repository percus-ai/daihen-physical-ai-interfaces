export function formatBytes(value: number | null | undefined): string {
  if (!value) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = value;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size.toFixed(size >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return '-';
  return `${value.toFixed(1)}%`;
}

const JAPAN_TIME_ZONE = 'Asia/Tokyo';

const dateTimeFormatter = new Intl.DateTimeFormat('ja-JP', {
  timeZone: JAPAN_TIME_ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23'
});

const UUID_PATTERN =
  /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

export function parseDateMs(value: string | null | undefined): number | null {
  if (!value) return null;
  const timestampMs = new Date(value).getTime();
  if (Number.isNaN(timestampMs)) return null;
  return timestampMs;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return dateTimeFormatter.format(date);
}

export function formatDurationMs(valueMs: number | null | undefined): string {
  if (valueMs === null || valueMs === undefined || valueMs < 0 || !Number.isFinite(valueMs)) {
    return '-';
  }

  const totalSeconds = Math.floor(valueMs / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (hours > 0) return `${hours}時間 ${minutes}分`;
  if (minutes > 0) return `${minutes}分 ${seconds}秒`;
  return `${seconds}秒`;
}

export function formatElapsedDuration(
  startValue: string | null | undefined,
  endValue: string | null | undefined,
  fallbackEndMs?: number
): string {
  const startMs = parseDateMs(startValue);
  if (startMs === null) return '-';

  const endMs = parseDateMs(endValue) ?? fallbackEndMs;
  if (endMs === undefined) return '-';

  return formatDurationMs(endMs - startMs);
}

export function formatUuidPreview(value: string | null | undefined): string {
  if (!value) return '-';
  const trimmed = value.trim();
  if (!UUID_PATTERN.test(trimmed)) return trimmed || '-';

  return trimmed.split('-').slice(0, 2).join('-');
}

export function formatRelativeDate(
  value: string | null | undefined,
  nowMs: number = Date.now()
): string {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  const diffMs = Math.max(0, nowMs - date.getTime());
  const diffMinutes = Math.floor(diffMs / (1000 * 60));
  if (diffMinutes < 1) return 'たった今';
  if (diffMinutes < 60) return `${diffMinutes}分前`;

  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}時間前`;

  const diffDays = Math.floor(diffHours / 24);
  if (diffDays > 30) return '30日超';
  return `${diffDays}日前`;
}
