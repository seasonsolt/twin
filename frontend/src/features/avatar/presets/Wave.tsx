import { Eyes, Mouth, type ArtProps } from './animation';
import { Suit } from './attire';

export function Wave({ blink, mouth }: ArtProps) {
  return (
    <>
      <rect width="220" height="220" fill="#DCE3EA" />
      <path
        d="M54 88 C40 140 46 168 58 180 L162 180 C174 168 180 140 166 88Z"
        fill="#3B2A24"
      />
      <Suit neck="#E9A985" jacket="#3A4250" lapel="#2B313C" shirt="#EEF1F5" />
      <ellipse cx="110" cy="104" rx="52" ry="60" fill="#F6C8A4" />
      <path
        d="M58 116 C46 56 80 34 112 36 C150 38 176 62 162 116 C158 94 152 78 140 68 C122 76 96 74 76 66 C66 80 60 96 58 116Z"
        fill="#3B2A24"
      />
      <path
        d="M58 100 C50 120 52 150 58 170 C64 160 64 130 62 110Z M162 100 C170 120 168 150 162 170 C156 160 156 130 158 110Z"
        fill="#3B2A24"
      />
      <path
        d="M78 94 Q88 90 98 93"
        stroke="#2E211C"
        strokeWidth="3.5"
        fill="none"
        strokeLinecap="round"
      />
      <path
        d="M122 93 Q132 90 142 94"
        stroke="#2E211C"
        strokeWidth="3.5"
        fill="none"
        strokeLinecap="round"
      />
      <Eyes blink={blink} y={110}>
        <ellipse cx="88" cy="110" rx="4.5" ry="5.5" fill="#2B1D18" />
        <ellipse cx="132" cy="110" rx="4.5" ry="5.5" fill="#2B1D18" />
        <circle cx="89.5" cy="108" r="1.5" fill="#fff" />
        <circle cx="133.5" cy="108" r="1.5" fill="#fff" />
      </Eyes>
      <path
        d="M108 120 Q111 127 114 125"
        stroke="#D28A66"
        strokeWidth="3"
        fill="none"
        strokeLinecap="round"
      />
      <Mouth level={mouth} y={140.25} color="#A9463F">
        <path
          className="mouth"
          d="M100 139 Q110 145 120 139"
          stroke="#A9463F"
          strokeWidth="3.5"
          fill="none"
          strokeLinecap="round"
        />
      </Mouth>
      <circle cx="58" cy="128" r="3.5" fill="#C9CED6" />
      <circle cx="162" cy="128" r="3.5" fill="#C9CED6" />
    </>
  );
}
