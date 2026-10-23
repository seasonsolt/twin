import { Avatar } from '../avatar/Avatar';
import type { Persona } from '../../stores/personas';

/** The twin's portrait or illustration; the first character of the name before there is a twin. */
export function PersonFace({
  name,
  twin,
  preset,
}: {
  name: string;
  twin?: Persona;
  /** The illustration the twin has just been given, ahead of the list of twins catching up. */
  preset?: string;
}) {
  if (!twin) return <>{Array.from(name)[0]}</>;
  return twin.avatar_url ? (
    <img src={twin.avatar_url} alt="" className="size-full object-cover" />
  ) : (
    <Avatar preset={preset ?? twin.avatar_preset} blinking={false} />
  );
}
