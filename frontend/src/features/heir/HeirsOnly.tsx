import { useState } from 'react';
import { Button, Stack, Text } from '../../components/ui';
import { HeirDoor } from './HeirDoor';

/**
 * The page once the person's own twin is sealed (P2.7): this computer is now the heirs' way in, and nothing of the
 * person's memory, will or settings is shown to anyone else. An heir gives their name and word and is in.
 */
export function HeirsOnly() {
  const [open, setOpen] = useState(false);
  return (
    <main className="flex h-dvh items-center justify-center px-4">
      <Stack gap={4} align="center">
        <Text tone="secondary">记忆已冻结</Text>
        <Button onClick={() => setOpen(true)}>我是继承人</Button>
      </Stack>
      <HeirDoor open={open} onOpenChange={setOpen} />
    </main>
  );
}
