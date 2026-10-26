import { useEffect, useState } from 'react';
import { Button, Dialog, Field, Input, Row, Text } from '../../components/ui';
import type { Person } from '../../pages/Recording';
import type { Persona } from '../../stores/personas';

/**
 * The work e-mail or employee number of the person a twin is made for: when they sign in with the company account
 * it names, the twin is theirs. Asked when the twin is made; changeable until they have taken it, and after that by an
 * administrator, which takes it from them.
 */
export function WorkClaim({
  person,
  twin,
  busy,
  error,
  onClose,
  onSave,
}: {
  person: Person | null;
  twin?: Persona;
  busy: boolean;
  /** Why saving failed: said here, where the owner is looking, with what was typed still in the field. */
  error?: string;
  onClose: () => void;
  onSave: (claim: string) => void;
}) {
  const [claim, setClaim] = useState('');
  useEffect(() => {
    if (person) setClaim(twin?.claim ?? '');
  }, [person, twin]);
  const making = !twin;
  return (
    <Dialog
      open={!!person}
      onOpenChange={(open) => !open && onClose()}
      title={
        making
          ? `为${person?.name ?? ''}建分身`
          : `${person?.name ?? ''}的企业邮箱或工号`
      }
      body="填 TA 企业账号的邮箱或工号，TA 一登录分身就归 TA。"
    >
      <form
        className="space-y-5"
        onSubmit={(event) => {
          event.preventDefault();
          onSave(claim.trim());
        }}
      >
        <Field
          id="work-claim"
          label={
            making ? '企业邮箱或工号（不知道可以先空着）' : '企业邮箱或工号'
          }
          help={
            twin?.claim_rejected
              ? `${twin.claim_rejected} 的主人说这不是 TA，换一个吧`
              : twin?.claimed
                ? '改绑或清空后，原认领人的私人内容会清掉。'
                : '对方登录前都能改。'
          }
        >
          <Input
            id="work-claim"
            autoComplete="off"
            maxLength={254}
            placeholder="name@company.com 或 12345"
            value={claim}
            onChange={(event) => setClaim(event.target.value)}
          />
        </Field>
        {error && (
          <Text role="alert" size="sm" tone="danger">
            {error}
          </Text>
        )}
        <Row gap={2} justify="end">
          <Button type="button" variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button
            type="submit"
            disabled={busy || (!making && !claim.trim() && !twin?.claim)}
          >
            {making ? '建好' : '保存'}
          </Button>
        </Row>
      </form>
    </Dialog>
  );
}
