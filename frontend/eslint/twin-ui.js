// Local ESLint rules that keep page and feature code on the components in src/components/ui: no hand-made form
// controls, no inline styles, and no class names that pick their own type size, corner radius, colour or arbitrary
// value. eslint.config.js lists the folders exempt from them and why.

const CONTROLS = {
  button:
    '页面里不要手写 <button>：改用 components/ui 的 Button / IconButton；像链接的按钮用 <TextLink onClick>，可切换的药丸用 Chip，整块可点的卡片用 <Card interactive>。',
  input:
    '页面里不要手写 <input>：改用 components/ui 的 Input、Checkbox、Radio；选文件用 FileDrop（拖放区）或 FileInput（由按钮打开）。',
  select: '页面里不要手写 <select>：改用 components/ui 的 Select。',
  textarea: '页面里不要手写 <textarea>：改用 components/ui 的 Textarea。',
};

// One Tailwind class, with optional variants (sm:, hover:, data-[x]:) and an optional opacity (/60).
const CLASS =
  /^!?(?:[a-z0-9-]+(?:-\[[^\]\s]+\])?:)*-?[a-z@][\w.-]*(?:-\[[^\]\s]+\])?(?:\/[\w.]+)?!?$/u;
const strip = (token) =>
  token.replace(/^!?(?:[a-z0-9-]+(?:-\[[^\]\s]+\])?:)*/u, '');

const CHECKS = [
  {
    test: (token) => /\[[^\]]*\]/u.test(strip(token)),
    message: (token) =>
      `不要用 Tailwind 任意值「${token}」：间距、尺寸、颜色只用 tokens.css 里的档位；表达不了就在 components/ui 里加组件或参数。`,
  },
  {
    test: (token) => /#[0-9a-f]{3,8}\b/iu.test(token),
    message: (token) =>
      `不要在 className 里写十六进制颜色「${token}」：用 tokens.css 的颜色（text-primary、bg-surface、text-accent 等）。`,
  },
  {
    test: (token) =>
      /^text-(?:xs|sm|base|md|lg|xl|[2-9]xl)$/u.test(strip(token)),
    message: (token) =>
      `不要直接写字号「${token}」：标题用 <Heading level>，正文用 <Text size="sm|md">，控件用组件的 size 参数。`,
  },
  {
    test: (token) => /^rounded(?:-[a-z0-9]+)*$/u.test(strip(token)),
    message: (token) =>
      `不要直接写圆角「${token}」：圆角由 components/ui 统一，选对应的组件：卡片 Card、列表行 ListRow、提示 Notice、标签 Badge / Chip、圆形头像 AvatarFrame、圆点 StatusDot、进度 Meter。`,
  },
];

function classStrings(node, found = []) {
  if (!node || typeof node !== 'object') return found;
  if (node.type === 'Literal' && typeof node.value === 'string')
    found.push({ node, value: node.value });
  else if (node.type === 'TemplateElement')
    found.push({ node, value: node.value.cooked ?? node.value.raw });
  else if (node.type === 'JSXElement' || node.type === 'JSXFragment')
    return found;
  for (const key of Object.keys(node)) {
    if (key === 'parent' || key === 'loc' || key === 'range') continue;
    const child = node[key];
    if (Array.isArray(child)) child.forEach((c) => classStrings(c, found));
    else if (child && typeof child.type === 'string')
      classStrings(child, found);
  }
  return found;
}

const CLASS_HELPERS = new Set(['cn', 'clsx', 'twMerge', 'cva']);
const looksLikeClasses = (value) => {
  const tokens = value.trim().split(/\s+/u).filter(Boolean);
  return tokens.length > 0 && tokens.every((token) => CLASS.test(token));
};

const noFreeStyle = {
  meta: {
    type: 'problem',
    docs: {
      description:
        '页面和功能代码不写 style、任意值、十六进制颜色、字号类和圆角类',
    },
    schema: [],
  },
  create(context) {
    const reported = new Set();
    const check = (node, value, inClassContext) => {
      if (reported.has(node)) return;
      if (!inClassContext && !looksLikeClasses(value)) return;
      for (const token of value.split(/\s+/u).filter(Boolean)) {
        const rule = CHECKS.find((candidate) => candidate.test(token));
        if (!rule) continue;
        reported.add(node);
        context.report({ node, message: rule.message(token) });
        return;
      }
    };
    return {
      JSXAttribute(node) {
        const name = node.name.name;
        if (name === 'style') {
          context.report({
            node,
            message:
              '页面里不要写 style 属性：外观交给 components/ui 的组件参数；确实要按数据变化的尺寸（进度、比例）就在 ui 里加组件，例如 Meter。',
          });
          return;
        }
        if (name !== 'className' && name !== 'class') return;
        for (const { node: literal, value } of classStrings(node.value))
          check(literal, value, true);
      },
      CallExpression(node) {
        if (
          node.callee.type !== 'Identifier' ||
          !CLASS_HELPERS.has(node.callee.name)
        )
          return;
        for (const argument of node.arguments)
          for (const { node: literal, value } of classStrings(argument))
            check(literal, value, true);
      },
      // Class lists kept in constants (`const task = 'flex rounded-xl …'`).
      Literal(node) {
        if (typeof node.value !== 'string') return;
        const parent = node.parent;
        if (
          parent?.type === 'ImportDeclaration' ||
          parent?.type === 'ExportNamedDeclaration' ||
          parent?.type === 'ExportAllDeclaration' ||
          parent?.type === 'ImportExpression' ||
          parent?.type === 'JSXAttribute'
        )
          return;
        check(node, node.value, false);
      },
      TemplateElement(node) {
        check(node, node.value.cooked ?? node.value.raw, false);
      },
    };
  },
};

const noRawControls = {
  meta: {
    type: 'problem',
    docs: {
      description:
        '页面和功能代码不手写 button / input / select / textarea，改用 components/ui',
    },
    schema: [],
  },
  create(context) {
    return {
      JSXOpeningElement(node) {
        if (node.name.type !== 'JSXIdentifier') return;
        const message = CONTROLS[node.name.name];
        if (message) context.report({ node, message });
      },
    };
  },
};

export default {
  meta: { name: 'twin-ui' },
  rules: {
    'no-raw-controls': noRawControls,
    'no-free-style': noFreeStyle,
  },
};
