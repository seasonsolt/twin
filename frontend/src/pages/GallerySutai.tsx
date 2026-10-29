import { useState } from 'react';
import {
  Button,
  CitationChip,
  GlassPanel,
  PillNav,
  RiseText,
  Row,
  Section,
  Stack,
  toast,
} from '../components/ui';
import { TwinCore } from '../components/effects';

const LINES = [
  '这是今年第三次。',
  '两句话都是你的，我不替你选。',
  '今晚不用决定。它让你先想到了谁？',
];

/** The 素体 pieces of the persona edition. Pick 体温, 琥珀 or 月光 above to see them in their own palette. */
export function SutaiStories() {
  const [said, setSaid] = useState(0);
  return (
    <Section title="素体">
      <Stack gap={4}>
        <PillNav
          items={[
            { to: '/gallery', label: '画廊' },
            { to: '/chat', label: '对话' },
            { to: '/memories', label: '记忆' },
          ]}
        />
        <GlassPanel padding="none" className="relative h-80 overflow-hidden">
          <TwinCore pulse={said} className="absolute inset-0 size-full" />
        </GlassPanel>
        <GlassPanel strong className="max-w-md">
          <Stack gap={3}>
            <RiseText key={said} size="lg">
              {LINES[said % LINES.length]}
            </RiseText>
            <Row gap={2} wrap>
              <CitationChip>日记 · 2024-01-27</CitationChip>
              <CitationChip onClick={() => toast('打开出处')}>
                聊天 · 2019-08-03
              </CitationChip>
              <CitationChip kind="conflict">矛盾 · 2</CitationChip>
            </Row>
          </Stack>
        </GlassPanel>
        <Row gap={3}>
          <Button variant="secondary" onClick={() => setSaid(said + 1)}>
            让它说话
          </Button>
        </Row>
      </Stack>
    </Section>
  );
}
