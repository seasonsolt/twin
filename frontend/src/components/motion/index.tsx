import {
  AnimatePresence,
  LayoutGroup,
  motion,
  type HTMLMotionProps,
  type PanInfo,
} from 'motion/react';
import { useId, type ReactNode } from 'react';
import { useMotionPreset } from '../../design/motion';

export function Pressable({ disabled, ...props }: HTMLMotionProps<'button'>) {
  const { reduced, transition } = useMotionPreset();
  return (
    <motion.button
      type="button"
      {...props}
      disabled={disabled}
      whileHover={
        reduced || disabled
          ? undefined
          : { y: -1, boxShadow: 'var(--elevation-2)' }
      }
      whileTap={reduced || disabled ? undefined : { scale: 0.97 }}
      transition={transition}
    />
  );
}

export function Reveal(props: HTMLMotionProps<'div'>) {
  const { reduced, transition, exit } = useMotionPreset('gentle');
  return (
    <motion.div
      variants={{
        hidden: { opacity: 0, y: reduced ? 0 : 8 },
        visible: { opacity: 1, y: 0, transition },
        exit: { opacity: 0, y: reduced ? 0 : -4, transition: exit },
      }}
      initial="hidden"
      animate="visible"
      exit="exit"
      {...props}
    />
  );
}

export function Stagger(props: HTMLMotionProps<'div'>) {
  const { reduced } = useMotionPreset();
  return (
    <motion.div
      variants={{
        hidden: {},
        visible: { transition: { staggerChildren: reduced ? 0 : 0.055 } },
      }}
      initial="hidden"
      animate="visible"
      exit="exit"
      {...props}
    />
  );
}

export function StaggerItem(props: HTMLMotionProps<'div'>) {
  const { reduced, transition, exit } = useMotionPreset('gentle');
  return (
    <motion.div
      variants={{
        hidden: { opacity: 0, y: reduced ? 0 : 8 },
        visible: { opacity: 1, y: 0, transition },
        exit: { opacity: 0, transition: exit },
      }}
      {...props}
    />
  );
}

export function PageTransition({
  route,
  children,
}: {
  route: string;
  children: ReactNode;
}) {
  const { reduced, transition } = useMotionPreset('gentle');
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div
        key={route}
        initial={{ opacity: 0, y: reduced ? 0 : 8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{
          opacity: 0,
          y: reduced ? 0 : -8,
          transition: { duration: 0.16 },
        }}
        transition={transition}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}

export function LayoutScope({ children }: { children: ReactNode }) {
  const id = useId();
  return <LayoutGroup id={id}>{children}</LayoutGroup>;
}

export function LayoutItem(props: HTMLMotionProps<'div'>) {
  const { reduced, transition } = useMotionPreset('layout');
  return <motion.div layout={!reduced} transition={transition} {...props} />;
}

export function shouldDismissDrag(offset: number, velocity: number) {
  return (
    Math.abs(offset) > 100 ||
    (Math.abs(offset) > 10 &&
      Math.abs(velocity) > 600 &&
      Math.sign(offset) === Math.sign(velocity))
  );
}

export function DragDismiss({
  onDismiss,
  children,
  ...props
}: HTMLMotionProps<'div'> & { onDismiss: () => void }) {
  const { reduced, transition } = useMotionPreset('layout');
  const end = (_: unknown, info: PanInfo) => {
    if (shouldDismissDrag(info.offset.x, info.velocity.x)) {
      onDismiss();
    }
  };
  return (
    <motion.div
      layout={!reduced}
      drag={reduced ? false : 'x'}
      dragConstraints={{ left: 0, right: 0 }}
      dragElastic={0.45}
      dragMomentum
      dragSnapToOrigin
      dragTransition={{
        bounceStiffness: 420,
        bounceDamping: 40,
        timeConstant: 220,
      }}
      onDragEnd={end}
      transition={transition}
      style={{ touchAction: 'pan-y' }}
      {...props}
    >
      {children}
    </motion.div>
  );
}
