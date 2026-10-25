import { toast, useConfirm } from '../../components/ui';
import { api } from '../../lib/api';
import { forgetPersona } from '../../lib/persona';
import { usePersonas, type Persona } from '../../stores/personas';

/** Whether the twin can be deleted at all: every one but a default twin still in use. */
export const deletable = (twin: Persona) =>
  twin.can_manage !== false && !(twin.is_default && !twin.retirable);

/**
 * Deleting a twin in one step. A deleted twin waits a week in the trash, so it goes at once and the toast offers to
 * undo it; only the empty leftover default twin, which is gone for good, asks first.
 */
export function useDeleteTwin() {
  const confirm = useConfirm();
  /** Resolves true once the twin is deleted; `onChange` runs after it is deleted, and again if it is restored. */
  return async (
    twin: Persona,
    onChange?: () => void | Promise<void>,
  ): Promise<boolean> => {
    if (!deletable(twin)) return false;
    if (
      twin.is_default &&
      !(await confirm({
        title: `删除「${twin.name}」？`,
        body: '它是空的，删除后不能恢复',
        confirmLabel: '删除分身',
        tone: 'danger',
      }))
    )
      return false;
    try {
      await api(`/api/personas/${encodeURIComponent(twin.id)}`, {
        method: 'DELETE',
      });
    } catch (failure) {
      toast(
        failure instanceof Error ? failure.message : '删除失败，请重试',
        'danger',
        8000,
      );
      return false;
    }
    forgetPersona(twin.id);
    await usePersonas.getState().refresh();
    await onChange?.();
    const restore = async () => {
      try {
        await api(`/api/personas/${encodeURIComponent(twin.id)}/restore`, {
          method: 'POST',
        });
      } catch (failure) {
        toast(
          failure instanceof Error ? failure.message : '没能撤销，请重试',
          'danger',
          8000,
        );
        return;
      }
      await usePersonas.getState().refresh();
      await onChange?.();
      toast(`已恢复「${twin.name}」`, 'success');
    };
    toast(
      `已删除「${twin.name}」`,
      'neutral',
      8000,
      twin.is_default
        ? undefined
        : { label: '撤销', onSelect: () => void restore() },
    );
    return true;
  };
}
