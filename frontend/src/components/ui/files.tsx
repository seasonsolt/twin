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
 * too. `label` names the region. `band` is one low strip that is itself the button: the standing way in on a page
 * that already has content.
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
  /** lg: the main call to action of an empty page; band: a strip above a page's content. */
  size?: 'md' | 'lg' | 'band';
  children?: ReactNode;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const band = size === 'band';
  return (
    <section
      aria-label={label}
      aria-disabled={disabled || undefined}
      data-drop-area=""
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
        band ? '' : size === 'lg' ? 'gap-4 px-6 py-12' : 'gap-3 p-6',
        over ? 'border-accent bg-soft' : 'border-border',
        disabled
          ? 'cursor-not-allowed opacity-60'
          : 'cursor-pointer hover:bg-soft',
      )}
    >
      {band ? (
        <button
          type="button"
          disabled={disabled}
          onClick={() => input.current?.click()}
          className="flex w-full items-center justify-center gap-4 rounded-lg px-6 py-5 text-left focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed"
        >
          <span className="grid size-12 shrink-0 place-items-center rounded-full bg-accent text-on-accent">
            <Upload aria-hidden className="size-6" />
          </span>
          <span className="flex flex-col gap-1">
            <span className="text-lg font-medium">
              {over ? '松开即可上传' : title}
            </span>
            {hint && <span className="text-sm text-secondary">{hint}</span>}
          </span>
        </button>
      ) : (
        <>
          <Upload
            aria-hidden
            className={cn(
              'text-secondary',
              size === 'lg' ? 'size-10' : 'size-8',
            )}
          />
          <p className={cn('font-medium', size === 'lg' && 'text-lg')}>
            {over ? '松开即可上传' : title}
          </p>
          <Button disabled={disabled} onClick={() => input.current?.click()}>
            {actionLabel}
          </Button>
          {hint && (
            <div className="space-y-1 text-sm text-secondary">{hint}</div>
          )}
        </>
      )}
      <FileInput
        ref={input}
        label={inputLabel ?? actionLabel}
        onFiles={onFiles}
        accept={accept}
        multiple={multiple}
        directory={directory}
        disabled={disabled}
      />
      {children}
    </section>
  );
}

/** A page-wide drop target; ordinary clicks keep their normal meaning. Files a drop area inside it took stay there. */
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
        setOver(false);
        if (event.defaultPrevented) return;
        event.preventDefault();
        if (!disabled) onFiles(Array.from(event.dataTransfer.files));
      }}
    >
      {children}
    </section>
  );
}

/**
 * Covers the page while files are dragged over it, to say where they would land: a dashed frame and `title`. It
 * takes no clicks or drops itself, so what lies under it still receives them.
 */
export function DropOverlay({ title }: { title: ReactNode }) {
  return (
    <div
      role="status"
      className="pointer-events-none fixed inset-0 z-50 grid place-items-center bg-canvas/80 p-6 backdrop-blur-sm"
    >
      <div className="flex w-full max-w-md flex-col items-center gap-3 rounded-lg border-2 border-dashed border-accent bg-surface px-6 py-12 text-center shadow-elevation-2">
        <Upload aria-hidden className="size-10 text-accent" />
        <p className="text-lg font-medium">{title}</p>
      </div>
    </div>
  );
}
