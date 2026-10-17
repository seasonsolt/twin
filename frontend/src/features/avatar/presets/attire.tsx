/** The shared business outfit: a jacket with lapels over a shirt or blouse, the neck, and an optional collar and
 * tie. Drawn before the head so the face and hair sit on top. */
export function Suit({
  neck,
  jacket,
  lapel,
  shirt,
  collar = false,
  tie,
}: {
  neck: string;
  jacket: string;
  lapel: string;
  shirt: string;
  collar?: boolean;
  tie?: string;
}) {
  return (
    <>
      <path
        d="M28 220 C32 172 68 158 110 158 C152 158 188 172 192 220Z"
        fill={jacket}
      />
      <path d="M88 160 L110 214 L132 160Z" fill={shirt} />
      <path
        d="M96 136 L124 136 L126 164 C116 172 104 172 94 164Z"
        fill={neck}
      />
      {collar && (
        <path
          d="M94 160 L110 172 L102 184 L88 166Z M126 160 L110 172 L118 184 L132 166Z"
          fill={shirt}
          stroke="#C4CCD8"
          strokeWidth="1.5"
          strokeLinejoin="round"
        />
      )}
      {tie && (
        <path
          d="M105 173 L115 173 L113 183 L107 183Z M107 183 L113 183 L118 206 L110 214 L102 206Z"
          fill={tie}
        />
      )}
      <path
        d="M84 162 L110 214 L96 186 L102 178Z M136 162 L110 214 L124 186 L118 178Z"
        fill={lapel}
      />
    </>
  );
}
