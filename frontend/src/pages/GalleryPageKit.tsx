import { useState } from 'react';
import { Mic, Plus, Sparkles } from 'lucide-react';
import {
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
  Meter,
  NavPill,
  Notice,
  Page,
  PlainButton,
  Radio,
  Row,
  Section,
  Select,
  Stack,
  Stat,
  StatusDot,
  StepNumber,
  Text,
  TextLink,
  toast,
  Toolbar,
  type Gap,
} from '../components/ui';

/** The page-level kit in the gallery: everything a page is built from, with no hand-written styles. */
export function PageKitStories({ disabled }: { disabled: boolean }) {
  const [gap, setGap] = useState<Gap>(3);
  const [who, setWho] = useState('');
  const [sample, setSample] = useState(true);
  const [mine, setMine] = useState('all');
  const [filters, setFilters] = useState(['决定']);
  return (
    <Stack gap={6}>
      <Card>
        <Page
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
            {(['raised', 'outline', 'note', 'soft'] as const).map((variant) => (
              <Card key={variant} variant={variant} padding="md">
                <Text size="sm">{variant}</Text>
              </Card>
            ))}
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
