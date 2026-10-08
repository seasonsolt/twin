import * as TabsPrimitive from '@radix-ui/react-tabs';
import * as SwitchPrimitive from '@radix-ui/react-switch';
import * as TooltipPrimitive from '@radix-ui/react-tooltip';
import { motion } from 'motion/react';
import { useId, useState, type ReactElement, type ReactNode } from 'react';
import { useMotionPreset } from '../../design/motion';
import { LayoutScope } from '../motion';

export function Tabs({
  items,
  defaultValue,
  scrollable = false,
}: {
  items: {
    value: string;
    label: ReactNode;
    content: ReactNode;
    disabled?: boolean;
  }[];
  defaultValue?: string;
  scrollable?: boolean;
}) {
  const [selected, setValue] = useState(defaultValue ?? items[0]?.value);
  const value = items.some((item) => item.value === selected)
    ? selected
    : (items.find((item) => item.value === defaultValue)?.value ??
      items[0]?.value);
  const { reduced, transition } = useMotionPreset('layout');
  const id = useId();
  return (
    <LayoutScope>
      <TabsPrimitive.Root value={value} onValueChange={setValue}>
        <TabsPrimitive.List
          aria-label="内容分类"
          className={`mb-4 gap-1 rounded-full border border-border bg-soft p-1 ${
            scrollable ? 'flex w-full min-w-0 overflow-x-auto' : 'inline-flex'
          }`}
        >
          {items.map((item) => (
            <TabsPrimitive.Trigger
              key={item.value}
              value={item.value}
              disabled={item.disabled}
              className={`relative min-h-11 rounded-full px-4 py-1.5 text-secondary data-[state=active]:text-canvas disabled:opacity-40 ${
                scrollable ? 'shrink-0 whitespace-nowrap' : ''
              }`}
            >
              {value === item.value && (
                <motion.span
                  layoutId={reduced ? undefined : `tab-${id}`}
                  initial={reduced ? { opacity: 0 } : false}
                  animate={{ opacity: 1 }}
                  transition={transition}
                  className="absolute inset-0 rounded-full bg-primary shadow-elevation-1"
                />
              )}
              <span className="relative">{item.label}</span>
            </TabsPrimitive.Trigger>
          ))}
        </TabsPrimitive.List>
        {items.map((item) => (
          <TabsPrimitive.Content key={item.value} value={item.value}>
            {item.content}
          </TabsPrimitive.Content>
        ))}
      </TabsPrimitive.Root>
    </LayoutScope>
  );
}

export function Switch({
  label,
  checked,
  onCheckedChange,
  disabled = false,
}: {
  label: string;
  checked: boolean;
  onCheckedChange?: (checked: boolean) => void;
  disabled?: boolean;
}) {
  const { reduced, transition } = useMotionPreset('snappy');
  const id = useId();
  return (
    <div className="flex items-center gap-3">
      <SwitchPrimitive.Root
        id={id}
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
        className="h-6 w-11 rounded-full bg-border p-0.5 data-[state=checked]:bg-accent disabled:opacity-40"
      >
        <SwitchPrimitive.Thumb asChild>
          <motion.span
            className="block size-5 rounded-full bg-surface shadow-elevation-1"
            style={reduced ? { x: checked ? 20 : 0 } : undefined}
            animate={reduced ? { opacity: [0.6, 1] } : { x: checked ? 20 : 0 }}
            transition={transition}
          />
        </SwitchPrimitive.Thumb>
      </SwitchPrimitive.Root>
      <label htmlFor={id}>{label}</label>
    </div>
  );
}

export function Tooltip({
  label,
  children,
}: {
  label: string;
  children: ReactElement;
}) {
  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          sideOffset={8}
          className="z-60 rounded-sm border border-border bg-surface-raised px-3 py-1.5 text-sm text-primary shadow-elevation-2"
        >
          {label}
          <TooltipPrimitive.Arrow className="fill-surface-raised" />
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}

export const TooltipProvider = TooltipPrimitive.Provider;
