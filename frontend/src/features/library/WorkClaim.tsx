import { useEffect, useState } from 'react';
import { Button, Dialog, Field, Input, Row, Text } from '../../components/ui';
import type { Person } from '../../pages/Recording';
import type { Persona } from '../../stores/personas';

/**
 * The work e-mail or employee number of the person a twin is made for: when they sign in with the company account
 * it names, the twin becomes theirs. Asked when the twin is made, and changeable until they have taken it.
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
      body="填 TA 企业账号的邮箱或工号。TA 一登录，分身就归到 TA 名下；TA 看过并点“没问题”之前，分身不对同事回答。"
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
              : '填错了也不要紧：对方登录后点“这不是我”，分身会退回给你。'
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
