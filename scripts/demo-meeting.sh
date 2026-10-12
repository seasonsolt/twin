#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != Darwin ]]; then
    echo '此演示仅支持 macOS，需要系统 say 和 ffmpeg。' >&2
    exit 1
fi
for tool in say ffmpeg ffprobe; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "缺少 $tool：say 由 macOS 提供；ffmpeg/ffprobe 请运行 brew install ffmpeg。" >&2
        exit 1
    fi
done
voices=()
while IFS= read -r voice; do
    voices+=("$voice")
done < <(say -v '?' | awk '/zh_(CN|TW)/ {
    sub(/[[:space:]]+zh_.*/, "")
    voice = $0
    sub(/[[:space:]]*\(.*/, "", voice)
    if (!seen[voice]++) print
}')
if [[ ${#voices[@]} -lt 2 ]]; then
    echo '需要两个不同的中文音色。请在系统设置 → 辅助功能 → 朗读内容中自行添加，再重试。' >&2
    echo "用 say -v '?' 查看音色；本脚本不会下载音色或模型。" >&2
    exit 1
fi
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
umask 077
mkdir -p data/demo
work_dir="$(mktemp -d "$repo_root/data/demo/.meeting.XXXXXX")"
trap 'rm -rf "$work_dir"' EXIT
lines=(
    '这是虚构示例会议，我是林舟。今天讨论纸灯计划的三张桌面卡片。先把问题说清楚，再走一小步。我建议先做可以修改的纸样，不要一次做完整套装。先听体验者卡在哪里，再决定下一步。'
    '我是岚禾，所有人物和项目都是虚构的。我整理了试用反馈。第二张卡片里的先定义问题太抽象，对方不知道怎么动笔。我担心时间不够，要不要今晚把二十张卡片都赶出来？'
    '谢谢你指出这个问题。我写得不够清楚，我来把那句话改成，写下你希望改变的一件小事。我不鼓励熬夜补计划的缺口。先缩小范围，只改最需要验证的三张，明天上午再一起看反馈。'
    '明白，我负责邀请两位自愿参加的体验者。还有一件事，试用时他们讲了自己的经历。我们能不能把完整记录放到公开展示里，让大家更容易理解这些卡片有什么用？'
    '必须先征得同意，再移除身份信息。你负责确认是否同意，我负责改成没有身份线索的摘要。没有得到同意的记录就不展示。我不同意的是方案，不是对人的评价。我们把担心写下来，再逐项核对。'
    '好，那就约定明天上午核对三张纸样和匿名摘要，今天不再增加范围。这是一段合成的虚构示例录音，用来验证说话人区分。我的任务是整理反馈和确认同意，林舟负责修改卡片。会议到这里结束。'
)
for i in "${!lines[@]}"; do
    voice="${voices[$((i % 2))]}"
    say -v "$voice" -r 190 -o "$work_dir/$i.aiff" "${lines[$i]}"
    ffmpeg -nostdin -hide_banner -loglevel error -y -i "$work_dir/$i.aiff" -ar 24000 -ac 1 "$work_dir/$i.wav"
    printf "file '%s.wav'\n" "$i" >> "$work_dir/concat.txt"
done
ffmpeg -nostdin -hide_banner -loglevel error -y -f concat -safe 1 -i "$work_dir/concat.txt" "$work_dir/full.wav"
duration="$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$work_dir/full.wav")"
# 两级调速保留音高，把完整对话控制在约 75 秒，不截断台词。
tempo="$(awk -v duration="$duration" 'BEGIN {if (duration <= 0) exit 1; printf "%.8f", sqrt(duration / 75)}')"
ffmpeg -nostdin -hide_banner -loglevel error -y -i "$work_dir/full.wav" -af "atempo=$tempo,atempo=$tempo" -c:a aac data/demo/meeting.m4a
ffmpeg -nostdin -hide_banner -loglevel error -y -i "$work_dir/0.wav" -c:a aac data/demo/linzhou-reference.m4a
echo "已生成约 75 秒的 data/demo/meeting.m4a，两个音色：${voices[0]}（林舟）、${voices[1]}（岚禾）。"
echo '这是虚构示例合成声音，不是真人录音；不会自动导入数据库。'
echo '开启转写后，切换到“示例·林舟”，到“记忆”页上传 meeting.m4a，验证说话人区分与“认出本人”。'
echo '验证声音匹配前，可在分身的声音设置中上传 data/demo/linzhou-reference.m4a 作为林舟的参考声音。'
echo '转写后端须支持说话人区分/参考声音匹配；不能仅凭台词自我介绍保证认出本人，请核对结果。'
