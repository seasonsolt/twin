import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...values: ClassValue[]) {
  return twMerge(clsx(values));
}

export function formatNumber(value: number) {
  return new Intl.NumberFormat('zh-CN').format(value);
}
