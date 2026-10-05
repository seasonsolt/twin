import { useRef, useState, type ReactNode } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { ArrowRight, Plus } from 'lucide-react';
import {
  Badge,
  Button,
  Card,
  Dialog,
  EmptyState,
  Field,
  IconButton,
  Input,
  Meter,
  Skeleton,
  Switch,
  Table,
  Tabs,
  Textarea,
  Tooltip,
  toast,
  useConfirm,
} from '../components/ui';
import {
  DragDismiss,
  LayoutItem,
  LayoutScope,
  PageTransition,
  Pressable,
  Reveal,
  Stagger,
  StaggerItem,
} from '../components/motion';
import { useMotionPreset } from '../design/motion';
import { useStatus } from '../stores/status';
import { formatNumber } from '../lib/utils';
import {
  ReplyReveal,
  ThinkingLabel,
  MetricNumber,
  MessageList,
  SpotlightAction,
  FlowStepper,
  SectionReveal,
} from '../components/effects';

function Story({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card className="space-y-5">
      <h2 className="text-lg font-semibold">{title}</h2>
      {children}
    </Card>
  );
}

export function Gallery() {
  const [disabled, setDisabled] = useState(false);
  const [checked, setChecked] = useState(true);
  const [message, setMessage] = useState('');
  const [meter, setMeter] = useState(64);
  const [dialog, setDialog] = useState(false);
  const [visible, setVisible] = useState(true);
  const [dragged, setDragged] = useState(false);
  const [reversed, setReversed] = useState(false);
  const [page, setPage] = useState('A');
  const trigger = useRef<HTMLElement | null>(null);
  const confirm = useConfirm();
  const { reduced, transition } = useMotionPreset('bouncy');
  const labels = useStatus((state) => state.data?.labels);
  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="mb-2 text-sm text-secondary">设计系统 / F0</p>
          <h1 className="text-2xl font-semibold">组件画廊</h1>
          <p className="mt-3 text-secondary">
            温暖的留白、安静的蓝色，以及自然的运动。
          </p>
        </div>
        <Badge tone="info">
          {reduced ? '减少动态效果：仅淡入淡出' : '弹簧动效已启用'}
        </Badge>
      </div>
      <Switch
        label="禁用交互控件"
        checked={disabled}
        onCheckedChange={setDisabled}
      />
      <div className="grid items-start gap-6 lg:grid-cols-2">
        <Story title="按钮与轻触反馈">
          <div className="flex flex-wrap gap-3">
            {(['primary', 'secondary', 'ghost', 'danger'] as const).map(
              (variant) => (
                <Button
                  key={variant}
                  variant={variant}
                  disabled={disabled}
                  onClick={() => toast(`按钮：${variant}`)}
                >
                  {variant}
                </Button>
              ),
            )}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button size="sm" disabled={disabled}>
              小按钮
            </Button>
            <Button size="md" disabled={disabled}>
              中按钮
            </Button>
            <Button size="lg" disabled={disabled}>
              大按钮
            </Button>
            <Button loading>处理中</Button>
            <Button disabled>不可用</Button>
            <Tooltip label="添加项目">
              <IconButton
                label="添加项目"
                disabled={disabled}
                onClick={() => toast('已添加示例项目', 'success')}
              >
                <Plus className="size-5" />
              </IconButton>
            </Tooltip>
          </div>
          <Pressable
            disabled={disabled}
            className="rounded-md border border-border px-4 py-2"
            onClick={() => toast('轻触反馈')}
          >
            Pressable · 悬停抬起 / 按下缩放
          </Pressable>
        </Story>
        <Story title="卡片与状态">
          <div className="grid gap-3 sm:grid-cols-2">
            <Card>
              <h3 className="font-semibold">静态卡片</h3>
              <p className="text-sm text-secondary">轻边框与硬偏移阴影。</p>
            </Card>
            <Card interactive onClick={() => toast('交互卡片')}>
              <h3 className="font-semibold">交互卡片</h3>
              <p className="text-sm text-secondary">支持键盘与轻触反馈。</p>
            </Card>
          </div>
          <div className="flex flex-wrap gap-2">
            {(['neutral', 'success', 'warning', 'danger', 'info'] as const).map(
              (tone) => (
                <Badge key={tone} tone={tone}>
                  {tone}
                </Badge>
              ),
            )}
          </div>
        </Story>
        <Story title="输入与字段">
          <Field
            id="gallery-name"
            label="名称"
            help="系统字体，适合中英文混排。"
          >
            <Input
              id="gallery-name"
              aria-describedby="gallery-name-description"
              placeholder="输入示例名称"
              disabled={disabled}
            />
          </Field>
          <Field id="gallery-error" label="错误状态" error="请输入有效的示例值">
            <Input
              id="gallery-error"
              aria-invalid
              aria-describedby="gallery-error-description"
              defaultValue="无效示例"
              disabled={disabled}
            />
          </Field>
          <Field
            id="gallery-message"
            label="消息"
            help="Enter 发送，Shift+Enter 换行；输入法组合时不会发送。"
          >
            <Textarea
              id="gallery-message"
              aria-describedby="gallery-message-description"
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              disabled={disabled}
              onSend={() => {
                if (message.trim()) {
                  toast('已发送示例消息', 'success');
                  setMessage('');
                }
              }}
            />
          </Field>
          <p className="text-xs text-secondary">{labels?.chat_notice}</p>
        </Story>
        <Story title="进度与加载">
          <Meter label="迁移进度示例" value={meter} />
          <Button
            variant="secondary"
            disabled={disabled}
            onClick={() => setMeter(meter === 64 ? 92 : 64)}
          >
            调整进度
          </Button>
          <div aria-label="加载中" className="space-y-3">
            <Skeleton className="h-6 w-2/3" />
            <Skeleton />
            <Skeleton className="w-4/5" />
          </div>
        </Story>
        <Story title="标签页与开关">
          <Tabs
            items={[
              {
                value: 'overview',
                label: '概览',
                content: (
                  <p className="text-secondary">共享布局指示器跟随当前标签。</p>
                ),
              },
              {
                value: 'details',
                label: '详情',
                content: (
                  <p className="text-secondary">
                    方向键可切换标签，内容随选择更新。
                  </p>
                ),
              },
              {
                value: 'disabled',
                label: '不可用',
                disabled: true,
                content: null,
              },
            ]}
          />
          <Switch
            label="示例设置"
            checked={checked}
            onCheckedChange={setChecked}
            disabled={disabled}
          />
          <Switch label="不可用设置" checked={false} disabled />
        </Story>
        <Story title="对话框、确认与通知">
          <div className="flex flex-wrap gap-3">
            <Button
              disabled={disabled}
              onClick={(event) => {
                trigger.current = event.currentTarget;
                setDialog(true);
              }}
            >
              打开对话框
            </Button>
            <Button
              variant="danger"
              disabled={disabled}
              onClick={async () => {
                const result = await confirm({
                  title: '移除示例？',
                  body: '此操作仅演示确认交互，不会修改真实数据。',
                  confirmLabel: '移除示例',
                  tone: 'danger',
                });
                toast(
                  result ? '已确认' : '已取消',
                  result ? 'success' : 'neutral',
                );
              }}
            >
              确认操作
            </Button>
            <Button
              variant="secondary"
              disabled={disabled}
              onClick={() => toast('这是一条可滑动关闭的通知', 'info')}
            >
              显示通知
            </Button>
          </div>
          <p className="text-sm text-secondary">
            Escape 关闭，焦点限制在对话框内，关闭后返回入口。
          </p>
          <Dialog
            open={dialog}
            onOpenChange={setDialog}
            title="轻量对话框"
            body="弹簧缩放与淡入淡出；背景模糊，支持键盘操作。"
            onCloseAutoFocus={(event) => {
              event.preventDefault();
              trigger.current?.focus();
            }}
          >
            <Button onClick={() => setDialog(false)}>完成</Button>
          </Dialog>
        </Story>
        <Story title="表格">
          <Table
            caption="示例任务状态"
            headers={['项目', '状态', '数量']}
            rows={[
              ['组件', <Badge tone="success">可用</Badge>, formatNumber(24)],
              ['页面', <Badge tone="warning">迁移中</Badge>, '5'],
            ]}
          />
        </Story>
        <Story title="空状态">
          <EmptyState title="还没有示例内容" body="这里留给下一次新的开始。">
            <Button
              variant="secondary"
              disabled={disabled}
              onClick={() => toast('这是一个空状态示例')}
            >
              添加内容 <ArrowRight className="size-4" />
            </Button>
          </EmptyState>
        </Story>
        <Story title="进入、离开与列表编排">
          <Button
            variant="secondary"
            disabled={disabled}
            onClick={() => setVisible(!visible)}
          >
            {visible ? '隐藏' : '显示'}示例
          </Button>
          <AnimatePresence>
            {visible && (
              <Reveal key="reveal">
                <Stagger className="space-y-2">
                  {['第一项', '第二项', '第三项'].map((item) => (
                    <StaggerItem
                      key={item}
                      className="rounded-md border border-border bg-canvas px-4 py-2"
                    >
                      {item}
                    </StaggerItem>
                  ))}
                </Stagger>
              </Reveal>
            )}
          </AnimatePresence>
        </Story>
        <Story title="布局与页面过渡">
          <div className="flex gap-2">
            <Button
              variant="secondary"
              disabled={disabled}
              onClick={() => setReversed(!reversed)}
            >
              重排布局
            </Button>
            <Button
              variant="secondary"
              disabled={disabled}
              onClick={() => setPage(page === 'A' ? 'B' : 'A')}
            >
              切换页面
            </Button>
          </div>
          <LayoutScope>
            <div className="flex gap-3">
              {(reversed ? ['B', 'A'] : ['A', 'B']).map((item) => (
                <LayoutItem
                  key={item}
                  className="grid size-14 place-items-center rounded-md border border-border bg-accent/5 text-accent"
                >
                  {item}
                </LayoutItem>
              ))}
            </div>
          </LayoutScope>
          <PageTransition route={page}>
            <p className="text-secondary">页面 {page} · 位移 8px 与淡入淡出</p>
          </PageTransition>
        </Story>
        <Story title="惯性拖动与回弹">
          <p className="text-sm text-secondary">
            横向拖动超过 100px，或快速甩动关闭；不足阈值时回弹。
          </p>
          <AnimatePresence>
            {!dragged && (
              <DragDismiss
                key="drag-demo"
                onDismiss={() => setDragged(true)}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="flex items-center justify-between rounded-lg border border-border bg-canvas p-4"
              >
                <span>试着拖动这张卡片</span>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setDragged(true)}
                >
                  关闭
                </Button>
              </DragDismiss>
            )}
          </AnimatePresence>
          {dragged && (
            <Button variant="secondary" onClick={() => setDragged(false)}>
              重新显示
            </Button>
          )}
        </Story>
        <Story title="轻快的点缀">
          <p className="text-sm text-secondary">
            bouncy 只用于轻松的示例反馈，不用于主要导航。
          </p>
          <motion.button
            type="button"
            disabled={disabled}
            whileTap={
              reduced || disabled ? undefined : { rotate: -8, scale: 0.9 }
            }
            transition={transition}
            className="rounded-xl border border-border bg-accent/5 px-5 py-3 text-accent disabled:opacity-50"
          >
            轻触试试
          </motion.button>
        </Story>
      </div>
      <ReactBitsGallery />
    </div>
  );
}

function EffectStory({
  title,
  note,
  children,
}: {
  title: string;
  note: string;
  children: ReactNode;
}) {
  const [replay, setReplay] = useState(0);
  return (
    <Story title={title}>
      <div key={replay}>{children}</div>
      <p className="text-sm text-secondary">减少动态效果：{note}</p>
      <Button
        variant="secondary"
        size="sm"
        onClick={() => setReplay(replay + 1)}
        aria-label={`重播 ${title}`}
      >
        重播
      </Button>
    </Story>
  );
}

function ListDemo() {
  const [extra, setExtra] = useState(false);
  return (
    <div className="space-y-3">
      <MessageList
        label="消息与资料示例"
        items={[
          { id: 'message', text: '消息：我会先整理已有资料。' },
          { id: 'source', text: '资料：一次访谈记录' },
          ...(extra ? [{ id: 'new', text: '新资料：一段日常记忆' }] : []),
        ]}
      />
      <Button size="sm" variant="secondary" onClick={() => setExtra(!extra)}>
        {extra ? '移除资料' : '添加资料'}
      </Button>
    </div>
  );
}

function ReactBitsGallery() {
  return (
    <section aria-labelledby="react-bits-heading" className="space-y-6">
      <h2 id="react-bits-heading" className="text-xl font-semibold">
        React Bits 动效
      </h2>
      <p className="text-secondary">
        短暂、局部的动效；页面只使用应用 wrapper，不直接依赖上游组件。
      </p>
      <div className="grid items-start gap-6 lg:grid-cols-2">
        <EffectStory
          title="BlurText · 助手回复"
          note="全文立即显示，不模糊、不逐词播放。"
        >
          <ReplyReveal text="我会先整理资料，再给出回答。 A quiet word-level reveal." />
        </EffectStory>
        <EffectStory title="ShinyText · 思考中" note="静态文字，不流动高光。">
          <ThinkingLabel />
        </EffectStory>
        <EffectStory
          title="CountUp · 指标"
          note="立即显示最终值，保留数字宽度。"
        >
          <div className="flex gap-8">
            <p>
              覆盖率 <MetricNumber value={86} suffix="%" />
            </p>
            <p>
              资料 <MetricNumber value={1280} />
            </p>
          </div>
        </EffectStory>
        <EffectStory
          title="AnimatedList · 消息与资料"
          note="直接显示列表，无缩放或交错；退出仅淡出。"
        >
          <ListDemo />
        </EffectStory>
        <EffectStory
          title="SpotlightCard · 交互卡片"
          note="关闭光斑；保留键盘与点击操作。"
        >
          <SpotlightAction
            label="查看示例资料"
            onClick={() => toast('这是示例资料', 'info')}
          >
            <h3 className="font-semibold">查看示例资料</h3>
            <p className="text-sm text-secondary">
              移动光标查看低强度蓝色光斑，也可用键盘打开。
            </p>
          </SpotlightAction>
        </EffectStory>
        <EffectStory
          title="Stepper · 多步流程"
          note="步骤直接切换，不滑动；按钮操作不变。"
        >
          <FlowStepper
            steps={[
              {
                id: 'intro',
                title: '准备',
                content: <p>第一步：确认准备情况。</p>,
              },
              {
                id: 'answer',
                title: '回答',
                content: <p>第二步：填写示例答案。</p>,
              },
              {
                id: 'review',
                title: '检查',
                content: <p>第三步：检查后完成。</p>,
              },
            ]}
            onComplete={() => toast('示例流程已完成', 'success')}
          />
        </EffectStory>
        <EffectStory
          title="AnimatedContent · 滚动揭示"
          note="内容立即可见，无位移或滚动触发动画。"
        >
          <SectionReveal>
            <p className="rounded-md border border-border bg-canvas p-4">
              滚动到这里时，区块轻移 8px 并淡入；重播会重新触发。
            </p>
          </SectionReveal>
        </EffectStory>
      </div>
    </section>
  );
}
