import { Button, Dialog, Row, Skeleton, Text } from '../../components/ui';
import { IdentityForm } from '../identity/IdentityForm';
import type { useIdentity } from '../identity/useIdentity';
import { usePersonaId } from '../../lib/usePersonaState';

/** The name and one-line introduction of the twin. */
export function EditIdentityDialog({
  open,
  onOpenChange,
  identity,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  identity: ReturnType<typeof useIdentity>;
}) {
  const personaId = usePersonaId();
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="名字与介绍">
      {identity.loading && <Skeleton className="h-40" />}
      {identity.error && (
        <Row gap={2} wrap role="alert">
          <Text tone="danger">{identity.error}</Text>
          <Button variant="secondary" onClick={identity.reload}>
            重试加载
          </Button>
        </Row>
      )}
      {identity.data && (
        <IdentityForm
          key={`${personaId}-${identity.data.name}-${identity.data.about}`}
          identity={identity.data}
          onSaved={() => {
            identity.reload();
            onOpenChange(false);
          }}
        />
      )}
    </Dialog>
  );
}
