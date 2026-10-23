import { Eyes, Mouth, type ArtProps } from './animation';
import { Suit } from './attire';
import { Face } from './face';

export function Bun({ blink, mouth }: ArtProps) {
  return (
    <>
      <rect width="220" height="220" fill="#DCDFE4" />
      <Suit
        neck="#D29C78"
        jacket="#5A6573"
        lapel="#4A5461"
        shirt="#F6F7F9"
        collar
      />
      <circle cx="110" cy="46" r="13" fill="#241D1B" />
      <Face skin="#E3AE8A" shade="#D29C78" deep="#C48D6A" jaw="soft" />
      <path
        d="M74 96 C70 60 88 44 110 44 C132 44 150 60 146 96 C144 80 138 68 128 62 C116 58 104 58 92 62 C82 68 76 80 74 96Z"
        fill="#241D1B"
      />
      <path
        d="M86 88 Q93 85 100 87"
        stroke="#241D1B"
        strokeWidth="2.2"
        fill="none"
        strokeLinecap="round"
      />
      <path
        d="M120 87 Q127 85 134 88"
        stroke="#241D1B"
        strokeWidth="2.2"
        fill="none"
        strokeLinecap="round"
      />
      <Eyes blink={blink} y={98}>
        <path d="M87 98 Q93 93.6 99 98 Q93 101 87 98Z" fill="#241D1B" />
        <path d="M121 98 Q127 93.6 133 98 Q127 101 121 98Z" fill="#241D1B" />
        <path
          d="M86 97.5 Q93 92.5 100 97 M120 97 Q127 92.5 134 97.5"
          stroke="#241D1B"
          strokeWidth="1.4"
          fill="none"
          strokeLinecap="round"
        />
      </Eyes>
      <path
        d="M110 104 L107 119 Q110 121 113 119"
        stroke="#B9805F"
        strokeWidth="1.8"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Mouth level={mouth} y={132} color="#844237">
        <path
          className="mouth"
          d="M102 131 Q110 134 118 131"
          stroke="#97564A"
          strokeWidth="2.6"
          fill="none"
          strokeLinecap="round"
        />
      </Mouth>
      <circle cx="76" cy="117" r="2" fill="#E6E8EC" />
      <circle cx="144" cy="117" r="2" fill="#E6E8EC" />
    </>
  );
}
