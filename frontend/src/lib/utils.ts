import { clsx, type ClassValue } from 'clsx';
import { extendTailwindMerge } from 'tailwind-merge';

// tailwind-merge only knows Tailwind's default scale: without this it takes text-md for a colour and drops it
// (or the colour) when both are given. Keep in step with @theme in design/tokens.css.
const twMerge = extendTailwindMerge({
  extend: {
    theme: {
      text: ['xs', 'sm', 'base', 'md', 'lg', 'xl', '2xl', '3xl'],
      radius: ['sm', 'md', 'lg', 'bubble', 'chat', 'full'],
    },
  },
});

export function cn(...values: ClassValue[]) {
  return twMerge(clsx(values));
}

export function formatNumber(value: number) {
  return new Intl.NumberFormat('zh-CN').format(value);
}
