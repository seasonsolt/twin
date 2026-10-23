/** The shared business outfit, cut as in a business headshot: a jacket with broad shoulders and notch lapels over a
 * shirt or blouse, the neck, and an optional collar and tie. Drawn before the head so the face and hair sit on top. */
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
        d="M4 220 C6 186 38 170 86 160 L110 158 L134 160 C182 170 214 186 216 220Z"
        fill={jacket}
      />
      <path d="M90 158 L110 208 L130 158Z" fill={shirt} />
      <path
        d="M98 136 L122 136 L123 160 C116 166 104 166 97 160Z"
        fill={neck}
      />
      <path
        d="M98 150 C104 156 116 156 122 150 L122 144 C116 149 104 149 98 144Z"
        fill="#000"
        fillOpacity=".12"
      />
      {collar && (
        <path
          d="M96 155 L110 168 L103 178 L89 161Z M124 155 L110 168 L117 178 L131 161Z"
          fill={shirt}
          stroke="#C4CCD8"
          strokeWidth="1"
          strokeLinejoin="round"
        />
      )}
      {tie && (
        <path
          d="M106 168 L114 168 L112.5 176 L107.5 176Z M107.5 176 L112.5 176 L117 204 L110 212 L103 204Z"
          fill={tie}
        />
      )}
      <path
        d="M88 158 L110 214 L78 190 L85 181 L73 177Z M132 158 L110 214 L142 190 L135 181 L147 177Z"
        fill={lapel}
      />
    </>
  );
}
