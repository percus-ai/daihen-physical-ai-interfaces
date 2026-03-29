export const DEFAULT_PAGE_SIZE = 10;

export const parsePageParam = (value: string | null | undefined): number => {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 1;
  const normalized = Math.floor(parsed);
  return normalized >= 1 ? normalized : 1;
};

export const resolvePageCount = (totalItems: number, pageSize: number): number => {
  const total = Math.max(0, Math.floor(Number(totalItems) || 0));
  const size = Math.max(1, Math.floor(Number(pageSize) || 1));
  return Math.max(1, Math.ceil(total / size));
};

export const clampPage = (page: number, totalItems: number, pageSize: number): number => {
  const normalized = parsePageParam(String(page));
  return Math.min(normalized, resolvePageCount(totalItems, pageSize));
};

export const buildPageHref = (currentUrl: URL, page: number): string => {
  const nextUrl = new URL(currentUrl);
  const normalizedPage = parsePageParam(String(page));
  if (normalizedPage <= 1) {
    nextUrl.searchParams.delete('page');
  } else {
    nextUrl.searchParams.set('page', String(normalizedPage));
  }
  return `${nextUrl.pathname}${nextUrl.search}${nextUrl.hash}`;
};

export const buildUrlWithQueryState = (
  currentUrl: URL,
  params: Record<string, string | number | null | undefined>
): string => {
  const nextUrl = new URL(currentUrl);
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === '') {
      nextUrl.searchParams.delete(key);
      continue;
    }
    nextUrl.searchParams.set(key, String(value));
  }
  return `${nextUrl.pathname}${nextUrl.search}${nextUrl.hash}`;
};

export const describePageRange = (currentPage: number, pageSize: number, totalItems: number): string => {
  const total = Math.max(0, Math.floor(Number(totalItems) || 0));
  if (total <= 0) {
    return '0件';
  }
  const normalizedPage = parsePageParam(String(currentPage));
  const size = Math.max(1, Math.floor(Number(pageSize) || 1));
  const start = (normalizedPage - 1) * size + 1;
  const end = Math.min(total, start + size - 1);
  return `${start}-${end} / ${total}件`;
};

export const buildVisiblePageNumbers = (currentPage: number, pageCount: number): number[] => {
  const normalizedCurrent = parsePageParam(String(currentPage));
  const normalizedPageCount = Math.max(1, Math.floor(Number(pageCount) || 1));
  const pages = new Set<number>([1, normalizedPageCount, normalizedCurrent - 1, normalizedCurrent, normalizedCurrent + 1]);
  return Array.from(pages)
    .filter((page) => page >= 1 && page <= normalizedPageCount)
    .sort((left, right) => left - right);
};
