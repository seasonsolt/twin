import { Eyes, Mouth, type ArtProps } from './animation';

export function Silver({ blink, mouth }: ArtProps) {
  return (
    <>
      <rect width="220" height="220" fill="#EFB7B3" />
      <circle cx="176" cy="46" r="24" fill="#F7D3D0" />
      <path
        d="M30 220 C34 174 70 160 110 160 C150 160 186 174 190 220Z"
        fill="#8E4F6E"
      />
      <path d="M88 160 C94 190 126 190 132 160Z" fill="#F4E6D8" />
      <path
        d="M88 162 L80 220 M132 162 L140 220"
        stroke="#6E3A55"
        strokeWidth="5"
      />
      <g fill="#FFF8EE">
        <circle cx="96" cy="176" r="3.5" />
        <circle cx="103" cy="181" r="3.5" />
        <circle cx="110" cy="183" r="3.5" />
        <circle cx="117" cy="181" r="3.5" />
        <circle cx="124" cy="176" r="3.5" />
      </g>
      <path
        d="M97 140 L123 140 L125 164 C115 170 105 170 95 164Z"
        fill="#E7AE8F"
      />
      <ellipse cx="110" cy="106" rx="52" ry="58" fill="#F5CDB2" />
      <path
        d="M54 118 C40 70 70 36 112 38 C154 40 182 72 164 118 C160 96 150 82 136 74 C130 86 116 90 104 84 C94 96 76 98 64 92 C58 100 56 108 54 118Z"
        fill="#E4E1E6"
      />
      <path
        d="M70 60 C88 46 120 44 140 54"
        stroke="#FFFFFF"
        strokeWidth="5"
        fill="none"
        strokeLinecap="round"
        opacity=".8"
      />
      <path
        d="M76 98 Q87 94 98 98"
        stroke="#9E97A6"
        strokeWidth="3.5"
        fill="none"
        strokeLinecap="round"
      />
      <path
        d="M122 98 Q133 94 144 98"
        stroke="#9E97A6"
        strokeWidth="3.5"
        fill="none"
        strokeLinecap="round"
      />
      <Eyes blink={blink} y={110.5}>
        <path
          d="M80 112 Q87 106 94 112"
          stroke="#3A2B2E"
          strokeWidth="4"
          fill="none"
          strokeLinecap="round"
        />
        <path
          d="M126 112 Q133 106 140 112"
          stroke="#3A2B2E"
          strokeWidth="4"
          fill="none"
          strokeLinecap="round"
        />
      </Eyes>
      <path
        d="M78 120 Q82 123 86 120 M134 120 Q138 123 142 120"
        stroke="#D99A84"
        strokeWidth="2"
        fill="none"
        strokeLinecap="round"
      />
      <circle cx="76" cy="130" r="10" fill="#E27E7A" opacity=".35" />
      <circle cx="144" cy="130" r="10" fill="#E27E7A" opacity=".35" />
      <path
        d="M107 120 Q110 127 114 125"
        stroke="#D2937A"
        strokeWidth="3"
        fill="none"
        strokeLinecap="round"
      />
      <Mouth level={mouth} y={141.5} color="#A3434A">
        <path
          className="mouth"
          d="M97 138 Q110 152 123 138"
          stroke="#A3434A"
          strokeWidth="4"
          fill="none"
          strokeLinecap="round"
        />
      </Mouth>
      <circle cx="58" cy="124" r="4" fill="#FFF8EE" />
      <circle cx="162" cy="124" r="4" fill="#FFF8EE" />
    </>
  );
}
