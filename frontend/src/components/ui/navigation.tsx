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
}: {
  items: {
    value: string;
    label: string;
    content: ReactNode;
    disabled?: boolean;
  }[];
  defaultValue?: string;
}) {
  const [value, setValue] = useState(defaultValue ?? items[0]?.value);
  const { reduced, transition } = useMotionPreset('layout');
  const id = useId();
  return (
    <LayoutScope>
      <TabsPrimitive.Root value={value} onValueChange={setValue}>
        <TabsPrimitive.List
          aria-label="内容分类"
          className="mb-4 inline-flex gap-1 rounded-md border border-border bg-canvas p-1"
        >
          {items.map((item) => (
            <TabsPrimitive.Trigger
              key={item.value}
              value={item.value}
              disabled={item.disabled}
              className="relative rounded-sm px-4 py-1.5 text-secondary data-[state=active]:text-primary disabled:opacity-40"
            >
              {value === item.value && (
                <motion.span
                  layoutId={reduced ? undefined : `tab-${id}`}
                  initial={reduced ? { opacity: 0 } : false}
                  animate={{ opacity: 1 }}
                  transition={transition}
                  className="absolute inset-0 rounded-sm bg-surface shadow-elevation-1"
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
