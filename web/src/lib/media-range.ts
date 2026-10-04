export interface ByteRange { start: number; end: number }
export const MAX_OPEN_RANGE_BYTES = 8 * 1024 * 1024;

export function limitOpenEndedRange(range: ByteRange | null, header: string | null): ByteRange | null {
  if (!range || !header || !/^bytes=\d+-$/i.test(header.trim())) return range;
  return { start: range.start, end: Math.min(range.end, range.start + MAX_OPEN_RANGE_BYTES - 1) };
}

export function parseRange(value: string | null, size: number): ByteRange | "invalid" | null {
  if (!value) return null;
  const match = /^bytes=(\d*)-(\d*)$/.exec(value.trim());
  if (!match || size === 0 || (!match[1] && !match[2])) return "invalid";
  let start: number; let end: number;
  if (!match[1]) {
    const suffixLength = Number(match[2]);
    if (!Number.isSafeInteger(suffixLength) || suffixLength <= 0) return "invalid";
    start = Math.max(0, size - suffixLength); end = size - 1;
  } else {
    start = Number(match[1]); end = match[2] ? Number(match[2]) : size - 1;
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start >= size || end < start) return "invalid";
    end = Math.min(end, size - 1);
  }
  return { start, end };
}
