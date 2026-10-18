import { useRef, useState, type ReactNode, type Ref } from 'react';
import { Upload } from 'lucide-react';
import { cn } from '../../lib/utils';
import { Button } from './controls';

/**
 * The native file chooser, out of sight but still reachable by keyboard and screen readers. Open it from a Button
 * with `ref.current?.click()`. Hands over the chosen files and clears itself, so the same file can be chosen again.
 */
export function FileInput({
  ref,
  label,
  onFiles,
  accept,
  multiple = false,
  directory = false,
  disabled = false,
}: {
  ref?: Ref<HTMLInputElement>;
  /** Accessible name of the chooser, such as "选择录音文件". */
  label: string;
  onFiles: (files: File[]) => void;
  accept?: string;
  multiple?: boolean;
  /** Choose a whole folder (its files arrive flattened). */
  directory?: boolean;
  disabled?: boolean;
}) {
  return (
    <input
      ref={ref}
      type="file"
      aria-label={label}
      accept={accept}
      multiple={multiple}
      disabled={disabled}
      className="sr-only"
      tabIndex={-1}
      {...(directory ? { webkitdirectory: '' } : {})}
      onChange={(event) => {
        const files = Array.from(event.currentTarget.files ?? []);
        event.currentTarget.value = '';
        onFiles(files);
      }}
    />
  );
}

/**
 * A dashed area to drop files on, with a button that opens the file chooser; clicking anywhere in the area opens it
 * too. `label` names the region.
 */
export function FileDrop({
  label,
  onFiles,
  accept,
  multiple = true,
  directory = false,
  disabled = false,
  title,
  actionLabel = '选择文件',
  inputLabel,
  hint,
  size = 'md',
  children,
}: {
  label: string;
  onFiles: (files: File[]) => void;
  accept?: string;
  multiple?: boolean;
  directory?: boolean;
  disabled?: boolean;
  /** What to do, such as "把会议录音拖到这里". While files are dragged over it says "松开即可上传". */
  title: ReactNode;
  actionLabel?: string;
  /** Accessible name of the hidden chooser; defaults to `actionLabel`. */
  inputLabel?: string;
  /** Small print under the button: formats, limits, who can see the files. */
  hint?: ReactNode;
  /** lg: the main call to action of an empty page. */
  size?: 'md' | 'lg';
  children?: ReactNode;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  return (
    <section
      aria-label={label}
      aria-disabled={disabled || undefined}
      onClick={(event) => {
        if (
          disabled ||
          (event.target as HTMLElement).closest('button, a, input')
        )
          return;
        input.current?.click();
      }}
      onDragEnter={(event) => {
        event.preventDefault();
        if (!disabled) setOver(true);
      }}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null))
          setOver(false);
      }}
      onDrop={(event) => {
        event.preventDefault();
        setOver(false);
        if (!disabled) onFiles(Array.from(event.dataTransfer.files));
      }}
      className={cn(
        'flex flex-col items-center rounded-lg border-2 border-dashed bg-surface text-center transition-colors',
        size === 'lg' ? 'gap-4 px-6 py-12' : 'gap-3 p-6',
        over ? 'border-accent bg-soft' : 'border-border',
        disabled
          ? 'cursor-not-allowed opacity-60'
          : 'cursor-pointer hover:bg-soft',
      )}
    >
      <Upload
        aria-hidden
        className={cn('text-secondary', size === 'lg' ? 'size-10' : 'size-8')}
      />
      <p className={cn('font-medium', size === 'lg' && 'text-lg')}>
        {over ? '松开即可上传' : title}
      </p>
      <Button disabled={disabled} onClick={() => input.current?.click()}>
        {actionLabel}
      </Button>
      <FileInput
        ref={input}
        label={inputLabel ?? actionLabel}
        onFiles={onFiles}
        accept={accept}
        multiple={multiple}
        directory={directory}
        disabled={disabled}
      />
      {hint && <div className="space-y-1 text-sm text-secondary">{hint}</div>}
      {children}
    </section>
  );
}

/** A page-wide drop target; ordinary clicks keep their normal meaning. */
export function FileDropSurface({
  fillPage = true,
  children,
  disabled,
  onFiles,
}: {
  fillPage?: boolean;
  children: ReactNode;
  disabled?: boolean;
  onFiles: (files: File[]) => void;
}) {
  const [over, setOver] = useState(false);
  return (
    <section
      aria-label="拖放上传录音"
      className={cn(
        fillPage && 'min-h-dvh',
        over && 'outline-2 outline-accent',
      )}
      onDragOver={(event) => {
        event.preventDefault();
        if (!disabled) setOver(true);
      }}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null))
          setOver(false);
      }}
      onDrop={(event) => {
        event.preventDefault();
        setOver(false);
        if (!disabled) onFiles(Array.from(event.dataTransfer.files));
      }}
    >
      {children}
    </section>
  );
}
