import type { ReactNode } from 'react';
import { AnimatePresence, motion, useIsPresent } from 'motion/react';
import { useMotionPreset } from '../../design/motion';
import { usePersonaId } from '../../lib/usePersonaState';

function Layer({
  children,
  duration,
}: {
  children: ReactNode;
  duration: number;
}) {
  const present = useIsPresent();
  return (
    <motion.div
      className="persona-fade-layer"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration }}
      aria-hidden={present ? undefined : true}
      inert={!present}
    >
      {children}
    </motion.div>
  );
}

export function PersonaFade({ children }: { children: ReactNode }) {
  const id = usePersonaId();
  const { reduced } = useMotionPreset();
  return (
    <div className="persona-fade">
      <AnimatePresence initial={false}>
        <Layer key={id} duration={reduced ? 0 : 0.2}>
          {children}
        </Layer>
      </AnimatePresence>
    </div>
  );
}
