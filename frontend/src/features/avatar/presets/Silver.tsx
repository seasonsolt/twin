import { Eyes, Mouth, type ArtProps } from './animation';
import { Suit } from './attire';

export function Silver({ blink, mouth }: ArtProps) {
  return (
    <>
      <rect width="220" height="220" fill="#CDD5E1" />
      <Suit neck="#E7AE8F" jacket="#3D4F6B" lapel="#2F3F57" shirt="#F4EFEA" />
      <g fill="#FBF8F2" stroke="#D8D2C8" strokeWidth="1">
        <circle cx="98" cy="171" r="3.2" />
        <circle cx="104" cy="175" r="3.2" />
        <circle cx="110" cy="176.5" r="3.2" />
        <circle cx="116" cy="175" r="3.2" />
        <circle cx="122" cy="171" r="3.2" />
      </g>
      <ellipse cx="110" cy="106" rx="52" ry="58" fill="#F5CDB2" />
      <path
        d="M54 118 C40 70 70 36 112 38 C154 40 182 72 164 118 C160 96 152 82 138 74 C120 82 96 82 78 76 C66 86 58 100 54 118Z"
        fill="#D9DBE0"
      />
      <path
        d="M72 60 C90 48 120 46 140 56"
        stroke="#F2F3F6"
        strokeWidth="4"
        fill="none"
        strokeLinecap="round"
      />
      <path
        d="M77 98 Q87 94 98 97"
        stroke="#8C8794"
        strokeWidth="3.5"
        fill="none"
        strokeLinecap="round"
      />
      <path
        d="M122 97 Q133 94 143 98"
        stroke="#8C8794"
        strokeWidth="3.5"
        fill="none"
        strokeLinecap="round"
      />
      <Eyes blink={blink} y={110.5}>
        <ellipse cx="88" cy="110.5" rx="4" ry="5" fill="#3A2B2E" />
        <ellipse cx="132" cy="110.5" rx="4" ry="5" fill="#3A2B2E" />
        <circle cx="89.3" cy="108.7" r="1.3" fill="#fff" />
        <circle cx="133.3" cy="108.7" r="1.3" fill="#fff" />
      </Eyes>
      <path
        d="M80 120 Q84 122 88 120 M132 120 Q136 122 140 120"
        stroke="#D99A84"
        strokeWidth="1.5"
        fill="none"
        strokeLinecap="round"
      />
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
          d="M99 140 Q110 147 121 140"
          stroke="#A3434A"
          strokeWidth="3.5"
          fill="none"
          strokeLinecap="round"
        />
      </Mouth>
      <circle cx="58" cy="124" r="3.5" fill="#FBF8F2" />
      <circle cx="162" cy="124" r="3.5" fill="#FBF8F2" />
    </>
  );
}
