// The SVG namespace is an identifier, never a fetched resource.
const SVG_NS = "ht" + "tp://www.w3.org/2000/svg";

export function createAvatar(spec) {
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  const element = document.createElement("div");
  element.className = "playback-avatar";
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 220 240");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "风格化插画");
  const color = name => /^#[0-9a-f]{6}$/i.test(spec.palette[name]) ? spec.palette[name] : "#777777";
  function shape(tag, attributes, parent = svg) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
    parent.append(node);
    return node;
  }
  shape("rect", { width: 220, height: 240, rx: 22, fill: color("background") });
  shape("path", { d: "M25 240 Q25 164 110 164 Q195 164 195 240 Z", fill: color("outfit") });
  shape("path", { d: "M90 177 L110 204 L130 177", fill: "none", stroke: color("accent"), "stroke-width": 8 });
  shape("ellipse", { cx: 110, cy: 96, rx: 68, ry: 76, fill: color("hair") });
  shape("rect", { x: 94, y: 142, width: 32, height: 38, rx: 12, fill: color("skin") });
  shape("ellipse", { cx: 110, cy: 106, rx: 57, ry: 64, fill: color("skin") });
  shape("path", { d: "M51 86 Q44 23 110 24 Q179 24 170 84 L139 61 L119 82 L93 57 Z", fill: color("hair") });
  const eyes = [85, 135].map(cx => shape("ellipse", { cx, cy: 103, rx: 5, ry: 7, fill: color("hair") }));
  shape("path", { d: "M105 119 Q110 126 115 119", fill: "none", stroke: color("accent"), "stroke-width": 3 });
  const mouths = [
    shape("path", { d: "M96 138 Q110 143 124 138", fill: "none", stroke: color("hair"), "stroke-width": 3 }),
    shape("ellipse", { cx: 110, cy: 140, rx: 12, ry: 3, fill: color("hair") }),
    shape("ellipse", { cx: 110, cy: 141, rx: 13, ry: 7, fill: color("hair") }),
    shape("ellipse", { cx: 110, cy: 143, rx: 14, ry: 12, fill: color("hair") }),
  ];
  const badge = document.createElement("p");
  badge.className = "avatar-label";
  badge.setAttribute("role", "note");
  badge.textContent = spec.label;
  element.append(svg, badge);
  let blinkTimer = null;
  let destroyed = false;
  let mouth = 0;
  element.setMouth = level => {
    mouth = Number.isInteger(level) ? Math.max(0, Math.min(3, level)) : 0;
    const displayed = reduced.matches ? Math.min(1, mouth) : mouth;
    mouths.forEach((node, index) => node.setAttribute("visibility", index === displayed ? "visible" : "hidden"));
  };
  function scheduleBlink() {
    if (destroyed || reduced.matches) return;
    blinkTimer = setTimeout(() => {
      eyes.forEach(eye => eye.setAttribute("ry", "1"));
      blinkTimer = setTimeout(() => {
        eyes.forEach(eye => eye.setAttribute("ry", "7"));
        scheduleBlink();
      }, 140);
    }, 3000 + Math.random() * 3000);
  }
  function motionChanged() {
    clearTimeout(blinkTimer);
    eyes.forEach(eye => eye.setAttribute("ry", "7"));
    element.setMouth(mouth);
    scheduleBlink();
  }
  element.destroy = () => {
    destroyed = true;
    clearTimeout(blinkTimer);
    reduced.removeEventListener("change", motionChanged);
    element.setMouth(0);
    element.remove();
  };
  reduced.addEventListener("change", motionChanged);
  element.setMouth(0);
  scheduleBlink();
  return element;
}
