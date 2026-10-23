import { Eyes, Mouth, type ArtProps } from './animation';
import { Suit } from './attire';
import { Face } from './face';

export function Wave({ blink, mouth }: ArtProps) {
  return (
    <>
      <rect width="220" height="220" fill="#D3D9E0" />
      <path
        d="M72 88 C64 128 66 158 76 176 L144 176 C154 158 156 128 148 88Z"
        fill="#34261F"
      />
      <Suit neck="#DBAD8E" jacket="#3B4452" lapel="#2E3541" shirt="#EEF1F5" />
      <Face skin="#EBC0A0" shade="#DBAD8E" deep="#CC9C7E" jaw="soft" />
      <path
        d="M74 100 C68 60 88 42 112 42 C136 42 154 60 146 102 C142 84 136 72 126 66 C112 62 100 66 96 60 C90 70 80 80 74 100Z"
        fill="#34261F"
      />
      <path
        d="M76 88 C70 118 72 146 80 166 L88 160 C82 140 80 116 83 94Z M144 88 C150 118 148 146 140 166 L132 160 C138 140 140 116 137 94Z"
        fill="#34261F"
      />
      <path
        d="M86 88 Q93 85 100 87"
        stroke="#34261F"
        strokeWidth="2.2"
        fill="none"
        strokeLinecap="round"
      />
      <path
        d="M120 87 Q127 85 134 88"
        stroke="#34261F"
        strokeWidth="2.2"
        fill="none"
        strokeLinecap="round"
      />
      <Eyes blink={blink} y={98}>
        <path d="M87 98 Q93 93.6 99 98 Q93 101 87 98Z" fill="#2A211D" />
        <path d="M121 98 Q127 93.6 133 98 Q127 101 121 98Z" fill="#2A211D" />
        <path
          d="M86 97.5 Q93 92.5 100 97 M120 97 Q127 92.5 134 97.5"
          stroke="#2A211D"
          strokeWidth="1.4"
          fill="none"
          strokeLinecap="round"
        />
      </Eyes>
      <path
        d="M110 104 L107 119 Q110 121 113 119"
        stroke="#C49478"
        strokeWidth="1.8"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Mouth level={mouth} y={132} color="#8A4740">
        <path
          className="mouth"
          d="M102 131 Q110 134 118 131"
          stroke="#A0584F"
          strokeWidth="2.6"
          fill="none"
          strokeLinecap="round"
        />
      </Mouth>
    </>
  );
}
