import type { ReactNode } from 'react';
import {
  ActionMenu,
  AvatarFrame,
  Button,
  Heading,
  Row,
  Stack,
  StatusDot,
  Text,
  TextLink,
  Toolbar,
  type ActionItem,
  type Tone,
} from '../../components/ui';

/** Where a member stands, as the header names it. */
export interface MemberStatus {
  label: string;
  tone: Tone;
}

/** Who this page is about: the way back to the team, their face and name, where their twin stands, a line about
 * them, and the one thing to do with them (talk to their twin) with the rest behind “⋯”. */
export function MemberHeader({
  name,
  you = false,
  about,
  face,
  status,
  badge,
  menu,
  primary,
}: {
  name: string;
  /** The page is the signed-in person's own. */
  you?: boolean;
  about?: string;
  face: ReactNode;
  status: MemberStatus;
  badge?: ReactNode;
  menu?: ActionItem[];
  /** The one thing to do next: talk to their twin, or make one. */
  primary?: { label: string; onClick: () => void };
}) {
  return (
    <Stack gap={4}>
      <Row as="nav" gap={2} aria-label="位置">
        <TextLink to="/team" size="sm">
          团队
        </TextLink>
        <Text as="span" size="sm" tone="tertiary" aria-hidden>
          /
        </Text>
        <Text as="span" size="sm" tone="secondary">
          {name}
          {you && '（你）'}
        </Text>
      </Row>
      <Toolbar as="header" gap={4}>
        <Row gap={4} grow>
          <AvatarFrame size="2xl">{face}</AvatarFrame>
          <Stack gap={1} grow>
            <Row gap={3} wrap>
              <Heading level={1} size="page">
                {name}
              </Heading>
              <Row gap={2}>
                <StatusDot tone={status.tone} />
                <Text as="span" size="sm">
                  {status.label}
                </Text>
              </Row>
              {badge}
            </Row>
            {about && (
              <Text size="sm" tone="secondary" truncate>
                {about}
              </Text>
            )}
          </Stack>
        </Row>
        <Row gap={2}>
          {menu && menu.length > 0 && (
            <ActionMenu label={`${name}的更多操作`} items={menu} />
          )}
          {primary && (
            <Button onClick={primary.onClick}>{primary.label}</Button>
          )}
        </Row>
      </Toolbar>
    </Stack>
  );
}
