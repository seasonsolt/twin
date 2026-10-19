import * as PopoverPrimitive from '@radix-ui/react-popover';
import * as TabsPrimitive from '@radix-ui/react-tabs';
import * as SwitchPrimitive from '@radix-ui/react-switch';
import * as TooltipPrimitive from '@radix-ui/react-tooltip';
import { motion } from 'motion/react';
import {
  useId,
  useRef,
  useState,
  type ComponentType,
  type ReactElement,
  type ReactNode,
} from 'react';
import { NavLink } from 'react-router';
import { useMotionPreset } from '../../design/motion';
import { LayoutScope } from '../motion';
import { cn } from '../../lib/utils';
import { Chip } from './controls';

export function Tabs({
  items,
  defaultValue,
  scrollable = false,
  variant = 'tabs',
  label = '内容分类',
  value: controlledValue,
  onValueChange,
}: {
  items: {
    value: string;
    label: ReactNode;
    content?: ReactNode;
    disabled?: boolean;
  }[];
  defaultValue?: string;
  scrollable?: boolean;
  /** filters: compact pressed pills controlling a list outside this component. */
  variant?: 'tabs' | 'filters';
  label?: string;
  value?: string;
  onValueChange?: (value: string) => void;
}) {
  const [selected, setValue] = useState(defaultValue ?? items[0]?.value);
  const chosen = controlledValue ?? selected;
  const value = items.some((item) => item.value === chosen)
    ? chosen
    : (items.find((item) => item.value === defaultValue)?.value ??
      items[0]?.value);
  const { reduced, transition } = useMotionPreset('layout');
  const id = useId();
  const change = (next: string) => {
    setValue(next);
    onValueChange?.(next);
  };
  if (variant === 'filters')
    return (
      <div
        role="group"
        aria-label={label}
        className="flex flex-wrap gap-1 rounded-full bg-soft p-1"
      >
        {items.map((item) => (
          <Chip
            key={item.value}
            pressed={value === item.value}
            disabled={item.disabled}
            onClick={() => change(item.value)}
          >
            {item.label}
          </Chip>
        ))}
      </div>
    );
  return (
    <LayoutScope>
      <TabsPrimitive.Root value={value} onValueChange={change}>
        <TabsPrimitive.List
          aria-label={label}
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

/**
 * A pill-shaped link in the app's navigation; the current page's is filled dark. `stacked` puts the icon above a
 * small label (the side rail), `inline` sets them side by side (the phone's bottom tabs). `indicator` names a
 * highlight that slides between the links sharing it (wrap them in a LayoutScope).
 */
export function NavPill({
  to,
  icon: Icon,
  label,
  layout = 'stacked',
  indicator,
}: {
  to: string;
  icon: ComponentType<{ className?: string; 'aria-hidden'?: boolean }>;
  label: string;
  layout?: 'stacked' | 'inline' | 'rail';
  indicator?: string;
}) {
  const { reduced, transition } = useMotionPreset('layout');
  const link = (
    <NavLink
      aria-label={layout === 'rail' ? label : undefined}
      to={to}
      className={({ isActive }) =>
        cn(
          'relative flex items-center justify-center',
          layout === 'rail' ? 'size-11 rounded-md' : 'rounded-full',
          layout === 'rail'
            ? 'text-secondary hover:bg-white/60'
            : layout === 'stacked'
              ? 'rail-link min-h-16 flex-col gap-1 text-xs text-primary'
              : 'min-h-11 gap-2 text-sm text-secondary',
          isActive &&
            (layout === 'rail'
              ? 'bg-surface text-primary shadow-elevation-1'
              : 'text-canvas'),
          isActive && layout === 'inline' && 'font-semibold',
          // Hover tint for the rail comes from .rail-link in tokens.css (fine pointers only).
          isActive && !indicator && layout !== 'rail' && 'bg-primary',
        )
      }
    >
      {({ isActive }) => (
        <>
          {isActive && indicator && layout !== 'rail' && (
            <motion.span
              layoutId={reduced ? undefined : indicator}
              initial={reduced ? { opacity: 0 } : false}
              animate={{ opacity: 1 }}
              transition={transition}
              className="absolute inset-0 rounded-full bg-primary"
            />
          )}
          <Icon aria-hidden className="relative size-5 shrink-0" />
          <span
            className={
              layout === 'rail' ? 'sr-only' : 'relative whitespace-nowrap'
            }
          >
            {label}
          </span>
        </>
      )}
    </NavLink>
  );
  return layout === 'rail' ? (
    <Tooltip label={label}>
      <span className="block">{link}</span>
    </Tooltip>
  ) : (
    link
  );
}

export interface AccountMenuItem {
  key: string;
  label: string;
  icon?: ComponentType<{ className?: string; 'aria-hidden'?: boolean }>;
  onSelect: () => void;
  /** Something there needs the user: a red dot on the item and on the account button, and these words. */
  alert?: string;
  danger?: boolean;
  disabled?: boolean;
}

/**
 * The account button at the foot of the rail and the menu it opens: who is signed in, then groups of items split by
 * a line (settings first, signing out last). Settings live here rather than on the rail, so the rail stays about the
 * work; an item that needs attention puts a red dot on the button.
 */
export function AccountMenu({
  name,
  detail,
  groups,
  error,
  theme,
}: {
  name: string;
  /** A second line under the name: the role or how they signed in. */
  detail?: string;
  groups: AccountMenuItem[][];
  /** Why the last action failed, shown under the items. */
  error?: string;
  /** A ThemePicker, on its own line under who is signed in. */
  theme?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const filled = groups.filter((group) => group.length > 0);
  const alert = filled.flat().find((item) => item.alert)?.alert;
  const initial = Array.from(name.trim() || '?')[0].toUpperCase();
  const avatar = (size: string) => (
    <span
      aria-hidden
      className={cn(
        'grid shrink-0 place-items-center rounded-full bg-primary text-canvas',
        size,
      )}
    >
      {initial}
    </span>
  );
  return (
    <PopoverPrimitive.Root open={open} onOpenChange={setOpen}>
      <PopoverPrimitive.Trigger asChild>
        <button
          ref={trigger}
          type="button"
          aria-label={alert ? `账户（${alert}）` : '账户'}
          className="relative mx-auto grid size-11 place-items-center rounded-full text-lg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          {avatar('size-11')}
          {alert && (
            <span
              aria-hidden
              data-account-alert=""
              className="absolute top-0 right-0 size-2.5 rounded-full bg-danger ring-2 ring-canvas"
            />
          )}
        </button>
      </PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          side="right"
          align="end"
          sideOffset={12}
          avoidCollisions
          collisionPadding={12}
          aria-label="账户"
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            trigger.current?.focus();
          }}
          className="account-popover z-50 w-[256px] rounded-lg border border-border bg-surface p-1.5 text-primary shadow-elevation-2"
        >
          <div className="flex items-center gap-3 px-2.5 py-2">
            {avatar('size-9 text-base')}
            <div className="min-w-0">
              <p className="truncate font-medium">{name}</p>
              {detail && <p className="text-sm text-secondary">{detail}</p>}
            </div>
          </div>
          {theme && (
            <div className="mt-1 flex items-center justify-between gap-2 border-t border-border pt-1 pl-2.5">
              <span className="text-sm text-secondary">主题</span>
              {theme}
            </div>
          )}
          {filled.map((group, index) => (
            <div
              key={group[0].key}
              className={cn(
                'grid',
                index === 0 && !theme
                  ? 'mt-1'
                  : 'mt-1 border-t border-border pt-1',
              )}
            >
              {group.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  disabled={item.disabled}
                  aria-label={
                    item.alert ? `${item.label}（${item.alert}）` : undefined
                  }
                  onClick={() => {
                    setOpen(false);
                    item.onSelect();
                  }}
                  className={cn(
                    'flex min-h-9 items-center gap-3 rounded-md px-2.5 text-left hover:bg-soft focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50',
                    item.danger ? 'text-danger' : 'text-primary',
                  )}
                >
                  {item.icon && (
                    <item.icon aria-hidden className="size-4 shrink-0" />
                  )}
                  <span className="flex-1">{item.label}</span>
                  {item.alert && (
                    <span className="flex items-center gap-1.5 text-xs text-secondary">
                      <span
                        aria-hidden
                        className="size-2 rounded-full bg-danger"
                      />
                      {item.alert}
                    </span>
                  )}
                </button>
              ))}
            </div>
          ))}
          {error && (
            <p role="alert" className="px-2.5 py-1.5 text-sm text-danger">
              {error}
            </p>
          )}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}

/** The first focusable thing on the page: hidden until focused, it moves focus to the element with `target`'s id. */
export function SkipLink({
  target,
  children,
}: {
  target: string;
  children: ReactNode;
}) {
  return (
    <a
      href={`#${target}`}
      onClick={(event) => {
        event.preventDefault();
        document.getElementById(target)?.focus();
      }}
      className="sr-only fixed top-2 left-2 z-70 rounded-md bg-surface p-2 focus:not-sr-only"
    >
      {children}
    </a>
  );
}
