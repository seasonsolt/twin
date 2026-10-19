import { useEffect, useRef, useState } from 'react';
import {
  Button,
  Chip,
  Field,
  Input,
  ListRow,
  Row,
  Stack,
  Text,
} from '../../components/ui';
import { api } from '../../lib/api';

interface Aliases {
  aliases: string[];
  fixed: string[];
  not_me: number;
}

/**
 * The names the person goes by in transcripts. Removing one gives its lines back to other people and those files are
 * sorted out again; adding one (a name confirmed as someone else by mistake) claims its lines in every transcript.
 */
export function AliasList() {
  const [value, setValue] = useState<Aliases | null>(null);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const mutation = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    api<Aliases>('/api/persona/aliases', { signal: controller.signal })
      .then(setValue)
      .catch((failure: unknown) => {
        if (!controller.signal.aborted)
          setError(failure instanceof Error ? failure.message : '无法读取称呼');
      });
    return () => {
      controller.abort();
      mutation.current?.abort();
    };
  }, []);
  const change = async (path: string, method: string, json?: unknown) => {
    if (mutation.current) return;
    const controller = new AbortController();
    mutation.current = controller;
    setBusy(true);
    setError('');
    try {
      const saved = await api<Aliases>(path, {
        method,
        json,
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      setValue(saved);
      setDraft('');
    } catch (failure) {
      if (!controller.signal.aborted)
        setError(failure instanceof Error ? failure.message : '保存失败');
    } finally {
      mutation.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  };
  return (
    <Stack as="section" gap={3} aria-label="转写稿里的称呼" aria-busy={busy}>
      <Text weight="semibold">转写稿里的称呼</Text>
      <Text size="sm" tone="secondary">
        会议记录里这些名字说的话算你的。删除后，相关记录会重新整理。
      </Text>
      {value && (
        <>
          <Row wrap>
            {value.fixed.map((name) => (
              <Chip key={name}>{name}</Chip>
            ))}
          </Row>
          {value.aliases.length > 0 && (
            <Stack as="ul" gap={1}>
              {value.aliases.map((name) => (
                <ListRow
                  key={name}
                  variant="divided"
                  title={name}
                  trailing={
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={busy}
                      aria-label={`删除称呼 ${name}`}
                      onClick={() =>
                        void change(
                          `/api/persona/aliases/${encodeURIComponent(name)}`,
                          'DELETE',
                        )
                      }
                    >
                      删除
                    </Button>
                  }
                />
              ))}
            </Stack>
          )}
          <Stack
            as="form"
            gap={2}
            onSubmit={(event) => {
              event.preventDefault();
              if (draft.trim())
                void change('/api/persona/aliases', 'POST', {
                  name: draft.trim(),
                });
            }}
          >
            <Field
              id="alias-name"
              label="添加称呼"
              help="例如稿里写的“林总”“小林”。"
            >
              <Input
                id="alias-name"
                maxLength={40}
                value={draft}
                disabled={busy}
                onChange={(event) => setDraft(event.target.value)}
              />
            </Field>
            <Row>
              <Button
                type="submit"
                size="sm"
                variant="secondary"
                disabled={busy || !draft.trim()}
              >
                添加
              </Button>
            </Row>
          </Stack>
        </>
      )}
      {error && (
        <Text role="alert" size="sm" tone="danger">
          {error}
        </Text>
      )}
    </Stack>
  );
}
