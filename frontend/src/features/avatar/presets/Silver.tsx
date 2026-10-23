import { Eyes, Mouth, type ArtProps } from './animation';
import { Suit } from './attire';
import { Face } from './face';

export function Silver({ blink, mouth }: ArtProps) {
  return (
    <>
      <rect width="220" height="220" fill="#CDD4DE" />
      <path
        d="M70 92 C64 124 68 146 78 152 L142 152 C152 146 156 124 150 92Z"
        fill="#A9AEB7"
      />
      <Suit neck="#DDB295" jacket="#33435C" lapel="#27354A" shirt="#F1ECE6" />
      <g fill="#F7F4EE" stroke="#D3CCC1" strokeWidth=".8">
        <circle cx="99" cy="159" r="2.6" />
        <circle cx="104" cy="163" r="2.6" />
        <circle cx="110" cy="164.5" r="2.6" />
        <circle cx="116" cy="163" r="2.6" />
        <circle cx="121" cy="159" r="2.6" />
      </g>
      <Face skin="#EEC6AC" shade="#DDB295" deep="#CFA286" jaw="soft" />
      <path
        d="M72 104 C66 62 88 42 112 42 C138 42 156 62 148 104 C144 86 138 74 128 68 C112 64 96 70 86 64 C80 76 74 88 72 104Z"
        fill="#BCC0C7"
      />
      <path
        d="M74 92 C70 116 72 140 80 152 L90 150 C82 132 80 112 80 96Z M146 92 C150 116 148 140 140 152 L130 150 C138 132 140 112 140 96Z"
        fill="#BCC0C7"
      />
      <path
        d="M90 58 C104 50 122 48 138 56"
        stroke="#D6D9DE"
        strokeWidth="1.6"
        fill="none"
        strokeLinecap="round"
      />
      <path
        d="M86 88 Q93 85.5 100 87"
        stroke="#8A8590"
        strokeWidth="2"
        fill="none"
        strokeLinecap="round"
      />
      <path
        d="M120 87 Q127 85.5 134 88"
        stroke="#8A8590"
        strokeWidth="2"
        fill="none"
        strokeLinecap="round"
      />
      <Eyes blink={blink} y={98}>
        <path d="M87 98 Q93 93.6 99 98 Q93 101 87 98Z" fill="#33282A" />
        <path d="M121 98 Q127 93.6 133 98 Q127 101 121 98Z" fill="#33282A" />
        <path
          d="M86 97.5 Q93 92.5 100 97 M120 97 Q127 92.5 134 97.5"
          stroke="#33282A"
          strokeWidth="1.3"
          fill="none"
          strokeLinecap="round"
        />
      </Eyes>
      <path
        d="M87 104 Q93 106 99 104 M121 104 Q127 106 133 104"
        stroke="#D4A68C"
        strokeWidth="1.1"
        fill="none"
        strokeLinecap="round"
      />
      <path
        d="M110 104 L107 119 Q110 121 113 119"
        stroke="#C69A80"
        strokeWidth="1.8"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Mouth level={mouth} y={132} color="#8A4548">
        <path
          className="mouth"
          d="M102 131 Q110 134 118 131"
          stroke="#9C5458"
          strokeWidth="2.6"
          fill="none"
          strokeLinecap="round"
        />
      </Mouth>
    </>
  );
}
