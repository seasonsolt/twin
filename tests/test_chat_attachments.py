from __future__ import annotations

from twin.persona.attachments import select_attachment_passages


def test_select_attachment_passages_prefers_relevant_excerpt_and_keeps_file_reference() -> None:
    text = "\n\n".join(
        [
            "项目背景：双方于春季开始合作。",
            "服务范围：供应商负责系统维护与日常支持。",
            "付款方式：服务费按季度支付。",
            "终止条件：任一方提前三十日书面通知即可解除合同。",
            "争议处理：双方先协商，协商不成提交仲裁。",
        ]
    )

    passages = select_attachment_passages([("服务合同.txt", text)], "合同终止条件是什么？")

    assert passages
    assert passages[0].file_name == "服务合同.txt"
    assert passages[0].citation_id == "file_1_p0004"
    assert "提前三十日书面通知" in passages[0].text
    assert passages[0].locator == "摘录 4"


def test_select_attachment_passages_includes_each_file_even_without_keyword_hits() -> None:
    passages = select_attachment_passages(
        [("会议纪要.txt", "周一讨论项目进度。"), ("预算.csv", "部门,预算\n产品,120")],
        "总结这些资料",
    )

    assert {passage.file_name for passage in passages} == {"会议纪要.txt", "预算.csv"}


def test_broad_file_question_samples_across_a_long_document() -> None:
    text = "\n\n".join(f"第{i}段内容没有与问题重合的词。" for i in range(1, 13))

    passages = select_attachment_passages([("材料.txt", text)], "总结这份文件")

    assert len(passages) == 8
    assert passages[0].locator == "摘录 1"
    assert any("第12段" in passage.text for passage in passages)
