import { useState } from 'react';
import {
  Activity,
  KeyRound,
  LogOut,
  Mic,
  Plus,
  Settings2,
  Sparkles,
} from 'lucide-react';
import {
  AspectRing,
  LevelDots,
  SideTabs,
  ChatSurface,
  ChatMessage,
  ChatAction,
  ChatInput,
  ChatIdentity,
  AudioPlayer,
  ClipButton,
  DecisionBar,
  FileDropSurface,
  FileInput,
  IdentityLink,
  RouteButton,
  Tabs,
  TaskRow,
  VoiceChoice,
  AccountMenu,
  ActionMenu,
  AvatarFrame,
  Badge,
  Button,
  Card,
  Checkbox,
  Chip,
  Clip,
  Disclosure,
  Field,
  FileDrop,
  Grid,
  Heading,
  HistoryBar,
  IconButton,
  Input,
  KeyValue,
  LinkButton,
  ListRow,
  LoadMore,
  Meter,
  NavPill,
  Notice,
  Page,
  PlainButton,
  Radio,
  Row,
  Section,
  Select,
  SettingsDialog,
  Dialog,
  Stack,
  Stat,
  StatusDot,
  StepNumber,
  Text,
  TextLink,
  ThemePicker,
  toast,
  Toolbar,
  ResizeHandle,
  type Gap,
} from '../components/ui';
import { THEMES, useTheme } from '../stores/theme';

/** The page-level kit in the gallery: everything a page is built from, with no hand-written styles. */
export function PageKitStories({ disabled }: { disabled: boolean }) {
  const [gap, setGap] = useState<Gap>(3);
  // The real palette: picking here recolours the whole gallery.
  const { theme, setTheme } = useTheme();
  const [side, setSide] = useState(false);
  const [who, setWho] = useState('');
  const [sample, setSample] = useState(true);
  const [mine, setMine] = useState('all');
  const [filters, setFilters] = useState(['决定']);
  const [settings, setSettings] = useState(false);
  const [section, setSection] = useState('monitor');
  const [sheetWidth, setSheetWidth] = useState(280);
  const [aspect, setAspect] = useState('D2');
  const [visibleRows, setVisibleRows] = useState(3);
  return (
    <Stack gap={6}>
      <Section title="人格画像">
        <Row gap={6} wrap>
          <AspectRing
            label="九个方面里已了解 6 个"
            segments={[3, 2, 1, 2, 0, 1, 1, 3, 0].map((level, i) => ({
              layer: i < 3 ? 'core' : i < 6 ? 'outer' : 'context',
              level,
            }))}
          >
            <Text size="xl" weight="semibold">
              6/9
            </Text>
            <Text size="xs" tone="secondary">
              个方面
            </Text>
          </AspectRing>
          <Stack gap={2}>
            {(['core', 'outer', 'context'] as const).map((layer, i) => (
              <Row key={layer} gap={3}>
                <LevelDots
                  level={i + 1}
                  layer={layer}
                  label={`等级 ${i + 1}`}
                />
                <Text size="sm">{['内核', '外显', '处境'][i]}</Text>
              </Row>
            ))}
          </Stack>
        </Row>
        <SideTabs
          label="九个方面（示例）"
          value={aspect}
          onValueChange={setAspect}
          groups={[
            {
              label: '内核',
              layer: 'core',
              items: [
                {
                  value: 'D2',
                  label: '看重什么',
                  trailing: <LevelDots level={3} />,
                },
                {
                  value: 'D4',
                  label: '怎么思考',
                  trailing: <LevelDots level={1} />,
                },
              ],
            },
            {
              label: '外显',
              layer: 'outer',
              items: [
                {
                  value: 'D6',
                  label: '说话方式',
                  trailing: <LevelDots level={2} layer="outer" />,
                },
              ],
            },
          ]}
        >
          <Text size="sm" tone="secondary">
            选中的方面：{aspect}
          </Text>
        </SideTabs>
      </Section>
      <Section title="聊天与导航">
        <Row gap={3}>
          <NavPill to="/gallery" icon={Mic} label="图标导航" layout="rail" />
          <ChatAction selected>形象</ChatAction>
        </Row>
        <ChatSurface variant="sheet" width={sheetWidth}>
          <Stack gap={2}>
            <ChatIdentity>
              <AvatarFrame size="fill">林</AvatarFrame>
            </ChatIdentity>
            <ChatAction variant="row">新对话</ChatAction>
          </Stack>
          <ResizeHandle
            label="示例：调整宽度"
            value={sheetWidth}
            min={220}
            max={440}
            defaultValue={280}
            onChange={setSheetWidth}
          />
        </ChatSurface>
        <ChatSurface variant="panel">
          <ChatMessage speaker="user">下周怎么安排？</ChatMessage>
          <ChatMessage speaker="twin" last>
            先确认团队的时间。
          </ChatMessage>
        </ChatSurface>
        <ChatSurface variant="composer">
          <ChatInput aria-label="示例消息" placeholder="聊点什么…" />
          <ChatAction variant="send" aria-label="示例发送" disabled>
            ↑
          </ChatAction>
        </ChatSurface>
        <ChatSurface variant="empty">
          <ChatIdentity size="empty">
            <AvatarFrame size="fill">林</AvatarFrame>
          </ChatIdentity>
          <Heading size="display" weight="bold">
            和林舟聊聊
          </Heading>
        </ChatSurface>
        <ChatSurface variant="stage">
          <Text tone="inherit">形象舞台</Text>
        </ChatSurface>
      </Section>
      <Card>
        <Page
          stackHeaderOnMobile
          titleSize="display"
          breadcrumb={<TextLink to="/gallery">上一级</TextLink>}
          title="页面骨架 Page"
          description="标题、一句说明、整页操作；手机上操作换到标题下方。"
          aside={<TextLink to="/gallery">返回上一级</TextLink>}
          actions={
            <Button disabled={disabled} onClick={() => toast('整页操作')}>
              <Mic aria-hidden className="size-4" />
              上传录音
            </Button>
          }
        >
          <Section
            title="分区 Section"
            description="小标题 + 内容；标题同时是这个区域的无障碍名称。"
            badge={<Badge tone="warning">3</Badge>}
            actions={
              <Button variant="secondary" size="sm" disabled={disabled}>
                分区操作
              </Button>
            }
          >
            <Text tone="secondary">
              framed
              版本放在描边卡片里，用于需要单独突出的一块（待办、危险操作）。
            </Text>
          </Section>
          <Section title="带框分区" framed>
            <Text>内容</Text>
          </Section>
        </Page>
      </Card>

      <Card className="space-y-4">
        <Heading level={3}>确认与筛选</Heading>
        <Tabs
          variant="filters"
          label="录音分类示例"
          value={mine}
          onValueChange={setMine}
          items={[
            { value: 'all', label: '全部 4' },
            { value: 'waiting', label: '待确认 2' },
          ]}
        />
        <IdentityLink
          to="/gallery"
          label="林舟的档案示例"
          onClick={() => toast('打开档案')}
        >
          <AvatarFrame size="sm">林</AvatarFrame>
          <Text>林舟 · 4 段录音</Text>
        </IdentityLink>
        <Row gap={3} wrap>
          <VoiceChoice
            selected={mine === 'voice'}
            onClick={() => setMine('voice')}
            disabled={disabled}
          >
            <AvatarFrame size="sm">林</AvatarFrame>林舟 · 声音像 71%
          </VoiceChoice>
          <RouteButton to="/gallery">确认说话人</RouteButton>
        </Row>
        <AudioPlayer aria-label="试听示例" />
        <FileDropSurface
          fillPage={false}
          onFiles={(files) => toast(`选了 ${files.length} 个文件`)}
        >
          <Text size="sm" tone="tertiary">
            把文件拖到此区域
          </Text>
          <FileInput
            label="文件选择示例"
            onFiles={(files) => toast(`选了 ${files.length} 个文件`)}
          />
        </FileDropSurface>
        <Stack as="ul" gap={0}>
          <ListRow variant="divided" stackOnMobile title="分隔行" />
          <ListRow variant="divided" title="分隔行" />
          <ListRow variant="dashed" title="接下来的说话人" />
        </Stack>
        <Notice tone="success" title="说话人都确认好了">
          相关的人会在后台重新整理记忆。
        </Notice>
        <DecisionBar>
          <Button disabled={disabled}>确认是林舟</Button>
          <Checkbox
            label="声音清楚，用作这个人的声纹样本"
            checked={sample}
            onChange={(event) => setSample(event.target.checked)}
          />
        </DecisionBar>
      </Card>
      <Grid columns={2} gap={6}>
        <Card className="space-y-5">
          <Heading level={3}>文字 Heading / Text / TextLink</Heading>
          <Stack gap={2}>
            <Heading level={4} size="display">
              display · 首次引导
            </Heading>
            <Heading level={4} size="page">
              page · 页面标题
            </Heading>
            <Heading level={4} size="section">
              section · 分区标题
            </Heading>
            <Heading level={4} size="item">
              item · 卡片标题
            </Heading>
          </Stack>
          <Stack gap={1}>
            <Text size="lg">lg · 16px 强调正文</Text>
            <Text>md · 14px 正文（默认）</Text>
            <Text size="sm" tone="secondary">
              sm · 13px 说明文字
            </Text>
            <Text size="xs" tone="tertiary">
              xs · 12px 角注
            </Text>
            <Text size="sm" tone="danger" role="alert">
              tone 只取语义颜色：secondary / tertiary / accent / success /
              warning / danger / info
            </Text>
          </Stack>
          <Row gap={4} wrap>
            <TextLink to="/gallery">站内链接</TextLink>
            <TextLink href="#/gallery" size="sm">
              小号链接
            </TextLink>
            <TextLink onClick={() => toast('像链接的按钮')} disabled={disabled}>
              像链接的按钮
            </TextLink>
          </Row>
        </Card>

        <Card className="space-y-5">
          <Heading level={3}>布局 Stack / Row / Toolbar / Grid</Heading>
          <Row gap={2} wrap>
            {([1, 2, 3, 4, 6] as const).map((step) => (
              <Chip
                key={step}
                pressed={gap === step}
                onClick={() => setGap(step)}
                disabled={disabled}
              >
                gap {step}
              </Chip>
            ))}
          </Row>
          <Row gap={gap} wrap>
            {['一', '二', '三', '四'].map((label) => (
              <Badge key={label}>{label}</Badge>
            ))}
          </Row>
          <Toolbar>
            <Text weight="medium">Toolbar：左边说明</Text>
            <Button size="sm" variant="secondary" disabled={disabled}>
              右边操作
            </Button>
          </Toolbar>
          <Grid columns={3} gap={gap}>
            {['甲', '乙', '丙'].map((label) => (
              <Card key={label} variant="soft" padding="md">
                <Text align="center">{label}</Text>
              </Card>
            ))}
          </Grid>
          <Text size="sm" tone="secondary">
            间距只能取 0/1/2/3/4/5/6/8 档（4px 为一档），不接受 className。
          </Text>
        </Card>

        <Card className="space-y-5">
          <Heading level={3}>滚动分页 LoadMore</Heading>
          <Stack as="ul" gap={2}>
            {Array.from({ length: Math.min(visibleRows, 9) }, (_, i) => (
              <ListRow key={i} title={`列表项目 ${i + 1}`} />
            ))}
          </Stack>
          <LoadMore
            shown={Math.min(visibleRows, 9)}
            total={9}
            disabled={disabled}
            onLoadMore={() => setVisibleRows((count) => count + 3)}
          />
          <Text size="sm" tone="secondary">
            靠近列表末尾时继续显示，也可以用按钮加载；已显示的项目留在原处。
          </Text>
        </Card>

        <Card className="space-y-5">
          <Heading level={3}>待办行 TaskRow</Heading>
          <Stack as="ul" gap={0}>
            <TaskRow
              leading={
                <ClipButton
                  size="md"
                  label="试听待办示例"
                  src="/api/library/recordings/demo/speakers/S1/samples/0"
                />
              }
              title="像林舟"
              meta="3 段录音 · 共说了 26 分钟 · 打开录音"
              hint="这段录音里已经有林舟，可能是同一个人被分成了两位"
              actionsWidth="field"
              actions={
                <>
                  <Input
                    aria-label="待办示例，是谁"
                    placeholder="这是谁"
                    className="min-w-0 flex-1"
                  />
                  <Button disabled={disabled}>确认</Button>
                  <ActionMenu
                    label="待办示例的更多选项"
                    items={[{ label: '不认识', onSelect: () => {} }]}
                  />
                </>
              }
            >
              <Row gap={2} wrap>
                <Chip onClick={() => toast('是林舟')}>是林舟</Chip>
              </Row>
            </TaskRow>
            <TaskRow
              leading={<StatusDot tone="danger" />}
              title="电话会议.amr"
              meta="10 月 12 日上传"
              actions={
                <Button variant="secondary" size="sm" disabled={disabled}>
                  重试
                </Button>
              }
            />
          </Stack>
          <Tabs
            label="带工具的标签示例"
            defaultValue="a"
            items={[
              { value: 'a', label: '人物 14', content: '人物的内容' },
              { value: 'b', label: '待处理 3' },
            ]}
            actions={<Input aria-label="找人示例" placeholder="找人" />}
          />
        </Card>

        <Card className="space-y-5">
          <Heading level={3}>列表行 ListRow</Heading>
          <Stack as="ul" gap={3}>
            <ListRow
              variant="outline"
              leading={<AvatarFrame size="md">林</AvatarFrame>}
              title={<TextLink to="/gallery">2026-10-15 产品周会.m4a</TextLink>}
              meta="57 分钟 · 4 位说话人"
              trailing={
                <>
                  <Badge tone="success">已认人</Badge>
                  <Button variant="ghost" size="sm" disabled={disabled}>
                    删除
                  </Button>
                </>
              }
            />
            <ListRow
              variant="outline"
              title="电话会议.amr"
              meta="转写失败"
              trailing={
                <Button variant="secondary" size="sm" disabled={disabled}>
                  重试
                </Button>
              }
            >
              <Text size="sm" tone="danger">
                无法读取音频，请换一种格式再试
              </Text>
            </ListRow>
          </Stack>
        </Card>

        <Card className="space-y-5">
          <Heading level={3}>选择 Select / Checkbox / Radio / Chip</Heading>
          <Field id="gallery-who" label="这是谁">
            <Select
              id="gallery-who"
              value={who}
              disabled={disabled}
              onChange={(event) => setWho(event.target.value)}
            >
              <option value="">请选择</option>
              <option value="linzhou">林舟</option>
              <option value="qinghe">许清禾</option>
            </Select>
          </Field>
          <Checkbox
            label="这段声音清楚，用作声纹样本"
            checked={sample}
            disabled={disabled}
            onChange={(event) => setSample(event.target.checked)}
          />
          <Stack gap={0} role="radiogroup" aria-label="哪段是我">
            <Radio
              name="gallery-mine"
              label="整段都是我"
              checked={mine === 'all'}
              disabled={disabled}
              onChange={() => setMine('all')}
            >
              <Badge tone="success">像你</Badge>
            </Radio>
            <Radio
              name="gallery-mine"
              label="都不是我（旁观资料）"
              checked={mine === 'none'}
              disabled={disabled}
              onChange={() => setMine('none')}
            />
          </Stack>
          <Row gap={2} wrap>
            {['决定', '承诺', '异议'].map((kind) => (
              <Chip
                key={kind}
                pressed={filters.includes(kind)}
                disabled={disabled}
                onClick={() =>
                  setFilters((current) =>
                    current.includes(kind)
                      ? current.filter((item) => item !== kind)
                      : [...current, kind],
                  )
                }
              >
                {kind}
              </Chip>
            ))}
            <Chip>只读标签</Chip>
          </Row>
        </Card>

        <Card className="space-y-5">
          <Heading level={3}>数字 Stat / KeyValue</Heading>
          <Grid columns={3}>
            <Stat label="记忆" value="48" hint="其中 1 条有矛盾" />
            <Stat label="录音" value="1.5 小时" />
            <Stat label="待确认" value="3" tone="warning" />
          </Grid>
          <KeyValue
            items={[
              ['负责人', '林舟 → 许清禾'],
              ['截止', '10 月 21 日'],
              ['来源', '2026-10-15 产品周会'],
            ]}
          />
          <KeyValue
            layout="inline"
            items={[
              ['状态', '进行中'],
              ['日期', '10 月 15 日'],
            ]}
          />
        </Card>

        <Card className="space-y-5">
          <Heading level={3}>提示与卡片 Notice / Card / AvatarFrame</Heading>
          <Notice>还没有配置能区分说话人的转写服务，录音会先排队。</Notice>
          <Notice
            tone="danger"
            role="alert"
            title="上传失败"
            actions={
              <Button size="sm" variant="secondary" disabled={disabled}>
                重试
              </Button>
            }
          >
            网络中断，已上传的部分会保留。
          </Notice>
          <Grid columns={2} gap={3}>
            {(['raised', 'outline', 'note', 'soft', 'plain'] as const).map(
              (variant) => (
                <Card key={variant} variant={variant} padding="md">
                  <Text size="sm">{variant}</Text>
                </Card>
              ),
            )}
          </Grid>
          <Row gap={3}>
            {(['sm', 'md', 'lg', 'xl'] as const).map((size) => (
              <AvatarFrame key={size} size={size}>
                周
              </AvatarFrame>
            ))}
          </Row>
        </Card>
      </Grid>

      <Grid columns={2} gap={6}>
        <Card className="space-y-4">
          <Heading level={3}>控件补充</Heading>
          <Field id="gallery-lg-input" label="突出的输入框 Input size=lg">
            <Input id="gallery-lg-input" size="lg" placeholder="邮箱" />
          </Field>
          <Field
            id="gallery-suggest-input"
            label="带候选的输入框 Input suggestions"
          >
            <Input
              id="gallery-suggest-input"
              placeholder="这是谁"
              suggestions={['林舟', '许清禾', '周石言']}
            />
          </Field>
          <Row gap={3}>
            <ClipButton
              label="试听片段 ClipButton"
              src="/api/library/recordings/demo/speakers/S1/samples/0"
            />
            <Text size="sm" tone="secondary">
              就地试听一小段声音 ClipButton
            </Text>
            <ClipButton
              label="对照试听 ClipButton caption"
              caption="听林舟"
              src="/api/library/recordings/demo/speakers/S2/samples/0"
            />
          </Row>
          <Row gap={2} wrap>
            <LinkButton href="#/gallery" variant="secondary" shape="pill">
              链接按钮 LinkButton
            </LinkButton>
            <IconButton label="圆形图标按钮" shape="circle" size="lg">
              <Plus aria-hidden className="size-5" />
            </IconButton>
            <ActionMenu
              label="更多操作示例"
              items={[
                { label: '重命名', onSelect: () => toast('重命名') },
                { label: '删除', onSelect: () => toast('删除') },
              ]}
            />
            <ThemePicker
              value={theme}
              options={THEMES}
              onChange={setTheme}
              named
            />
            <AccountMenu
              name="周石言"
              detail="管理员"
              theme={
                <ThemePicker
                  value={theme}
                  options={THEMES}
                  onChange={setTheme}
                />
              }
              groups={[
                [
                  {
                    key: 'system',
                    label: '系统设置',
                    icon: Settings2,
                    alert: '1 项服务异常',
                    onSelect: () => toast('打开系统设置'),
                  },
                ],
                [
                  {
                    key: 'logout',
                    label: '退出登录',
                    icon: LogOut,
                    danger: true,
                    onSelect: () => toast('退出登录'),
                  },
                ],
              ]}
            />
          </Row>
          <Meter label="读资料进度" value={42} max={60} />
          <Meter label="细进度条" value={18} max={60} size="sm" hideLabel />
          <Disclosure summary="展开说明 Disclosure" variant="outline">
            <Text size="sm" tone="secondary">
              收起的细节放在这里。
            </Text>
          </Disclosure>
        </Card>
        <Card className="space-y-4">
          <Heading level={3}>外壳与媒体</Heading>
          <Row gap={3}>
            <PlainButton
              shape="circle"
              aria-label="外壳里的头像按钮 PlainButton"
              className="size-12 hover:bg-soft"
              onClick={() => toast('切换分身')}
            >
              <AvatarFrame size="fill" outlined>
                周
              </AvatarFrame>
            </PlainButton>
            <NavPill to="/gallery" icon={Sparkles} label="导航" />
            <StepNumber>1</StepNumber>
            <StepNumber size="sm" state="done">
              1
            </StepNumber>
            <StepNumber size="sm" state="current">
              2
            </StepNumber>
            <StepNumber size="sm" state="pending">
              3
            </StepNumber>
            <StatusDot tone="success" />
          </Row>
          <HistoryBar
            label="每小时检查结果示例 HistoryBar"
            slots={(
              [
                'success',
                'success',
                'warning',
                'success',
                'danger',
                'none',
              ] as const
            ).map((tone, i) => ({ key: i, tone, title: `第 ${i + 1} 小时` }))}
          />
          <Text size="xl">控件里的名字 Text xl</Text>
          <Text size="2xl">卡片里的名字 Text 2xl</Text>
          <Clip shape="card">
            <div className="grid h-24 place-items-center bg-primary text-canvas">
              Clip：给视频、3D 视图裁圆角
            </div>
          </Clip>
        </Card>
      </Grid>

      <Card className="space-y-4">
        <Heading level={3}>设置弹窗 SettingsDialog</Heading>
        <Text size="sm" tone="secondary">
          次要任务盖在当前页面上打开，关闭后回到原处；左侧菜单分组，异常只用一个红点提示。
        </Text>
        <Row gap={2}>
          <Button
            variant="secondary"
            disabled={disabled}
            onClick={() => setSettings(true)}
          >
            打开设置弹窗
          </Button>
        </Row>
        <Text size="sm" tone="secondary">
          侧层 Dialog
          variant=&quot;side&quot;：贴在右边、整屏高，用来在页面旁边读一样东西（回答的依据），关闭后页面还在原处。
        </Text>
        <Row gap={2}>
          <Button
            variant="secondary"
            disabled={disabled}
            onClick={() => setSide(true)}
          >
            打开侧层
          </Button>
        </Row>
        <Dialog
          open={side}
          onOpenChange={setSide}
          title="回答依据"
          variant="side"
        >
          <Text size="sm">
            产品周会 · 10 月 15 日：“先把上线日期定下来，再排人。”
          </Text>
        </Dialog>
        <SettingsDialog
          open={settings}
          onOpenChange={setSettings}
          title="系统"
          note="仅管理员可见"
          active={section}
          onSelect={setSection}
          sections={[
            {
              key: 'monitor',
              label: '监控',
              icon: Activity,
              status: { label: '1 项异常', tone: 'danger' },
            },
            {
              key: 'tts',
              label: '朗读服务',
              group: '服务',
              status: { label: '已关闭' },
            },
            {
              key: 'tokens',
              label: '模型与 Token',
              group: '设置',
              icon: KeyRound,
            },
          ]}
        >
          <Text>当前分区：{section}</Text>
        </SettingsDialog>
      </Card>

      <Card className="space-y-5">
        <Heading level={3}>文件拖放 FileDrop</Heading>
        <FileDrop
          label="添加录音示例"
          title="把会议录音拖到这里"
          inputLabel="选择示例录音"
          disabled={disabled}
          hint="音频或视频都可以，一次可以选多个。"
          onFiles={(files) => toast(`选了 ${files.length} 个文件`)}
        />
      </Card>
    </Stack>
  );
}
