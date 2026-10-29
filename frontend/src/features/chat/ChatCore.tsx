import { TwinCore } from '../../components/effects';

/**
 * The 素体 core above a persona twin's chat. It stands large over an empty chat and settles into a band once
 * something has been said (the page's data-empty decides, in chat.css), and pulses with each message as it comes.
 */
export function ChatCore({
  pulse,
  thinking,
}: {
  /** Goes up by one for each message; every step is a pulse. */
  pulse: number;
  thinking: boolean;
}) {
  return (
    <div className="chat-core" data-thinking={thinking || undefined}>
      <TwinCore
        pulse={pulse}
        label={thinking ? '分身正在想' : '分身的心核'}
        className="size-full"
      />
    </div>
  );
}
