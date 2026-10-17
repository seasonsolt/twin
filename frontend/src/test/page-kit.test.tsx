import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import {
  Checkbox,
  FileDrop,
  ListRow,
  Page,
  Section,
  Select,
  Text,
  TextLink,
} from '../components/ui';
import { cn } from '../lib/utils';

describe('page kit', () => {
  it('names a section region by its title and gives the page one heading', () => {
    render(
      <Page title="团队" description="会议里出现过的人。">
        <Section title="需要你处理">
          <p>内容</p>
        </Section>
      </Page>,
    );
    expect(
      screen.getByRole('heading', { level: 2, name: '团队' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('region', { name: '需要你处理' }),
    ).toBeInTheDocument();
  });

  it('renders a text link as a route, an address or a button', async () => {
    const onClick = vi.fn();
    render(
      <MemoryRouter>
        <TextLink to="/team">返回团队</TextLink>
        <TextLink href="https://example.com">外部</TextLink>
        <TextLink onClick={onClick}>恢复原样</TextLink>
      </MemoryRouter>,
    );
    expect(screen.getByRole('link', { name: '返回团队' })).toHaveAttribute(
      'href',
      '/team',
    );
    expect(screen.getByRole('link', { name: '外部' })).toHaveAttribute(
      'href',
      'https://example.com',
    );
    await userEvent.click(screen.getByRole('button', { name: '恢复原样' }));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it('hands dropped and chosen files over, and ignores them while disabled', () => {
    const onFiles = vi.fn();
    const file = new File(['a'], 'a.m4a', { type: 'audio/mp4' });
    const { rerender } = render(
      <FileDrop
        label="添加录音"
        title="拖到这里"
        inputLabel="选择录音文件"
        onFiles={onFiles}
      />,
    );
    fireEvent.drop(screen.getByRole('region', { name: '添加录音' }), {
      dataTransfer: { files: [file] },
    });
    fireEvent.change(screen.getByLabelText('选择录音文件'), {
      target: { files: [file] },
    });
    expect(onFiles).toHaveBeenCalledTimes(2);
    expect(onFiles).toHaveBeenLastCalledWith([file]);
    rerender(
      <FileDrop label="添加录音" title="拖到这里" onFiles={onFiles} disabled />,
    );
    fireEvent.drop(screen.getByRole('region', { name: '添加录音' }), {
      dataTransfer: { files: [file] },
    });
    expect(onFiles).toHaveBeenCalledTimes(2);
    expect(screen.getByRole('button', { name: '选择文件' })).toBeDisabled();
  });

  it('labels a checkbox by its text and a select by aria-label', async () => {
    const onChange = vi.fn();
    render(
      <>
        <Checkbox label="用作声纹样本" checked={false} onChange={onChange} />
        <Select aria-label="这是谁" defaultValue="">
          <option value="">请选择</option>
          <option value="a">林舟</option>
        </Select>
      </>,
    );
    await userEvent.click(screen.getByText('用作声纹样本'));
    expect(onChange).toHaveBeenCalledOnce();
    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: '这是谁' }),
      'a',
    );
    expect(screen.getByRole('combobox', { name: '这是谁' })).toHaveValue('a');
  });

  it('lays a list row out as a list item with its actions', () => {
    render(
      <ul>
        <ListRow
          title="周会.m4a"
          meta="57 分钟"
          trailing={<button>删除</button>}
        />
      </ul>,
    );
    expect(screen.getByRole('listitem')).toHaveTextContent(
      '周会.m4a57 分钟删除',
    );
  });

  it('keeps one type size when sizes are merged, and colours beside sizes', () => {
    expect(cn('text-sm', 'text-md')).toBe('text-md');
    expect(cn('text-md text-accent')).toBe('text-md text-accent');
    render(
      <Text size="sm" tone="secondary">
        说明
      </Text>,
    );
    expect(screen.getByText('说明')).toHaveClass('text-sm', 'text-secondary');
  });
});
