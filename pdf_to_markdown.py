# -*- coding: utf-8 -*-
"""
将《模块二撰写要求》PDF 转换为结构化 Markdown
- 保留章节编号（2.3.P.x.x.x）
- 保留【关注点】【示例】标记
- 表格转为标准 Markdown 表格
"""
import re
import pdfplumber
from pathlib import Path

PDF_FILE = Path("化学药品仿制药上市许可申请模块二药学资料撰写要求（制剂）（试行）.pdf")
OUTPUT_MD = Path("module2.md")


def main():
    if not PDF_FILE.exists():
        raise FileNotFoundError(f"PDF 文件不存在: {PDF_FILE}")

    markdown_lines = []
    with pdfplumber.open(PDF_FILE) as pdf:
        for page in pdf.pages:
            text = page.extract_text(x_tolerance=1, y_tolerance=1)
            if not text:
                continue

            # 按行处理
            for line in text.split('\n'):
                line = line.strip()
                if not line:
                    continue

                # 1. 章节标题（2.3.P.x.x.x）
                if re.fullmatch(r'2\.3\.P(\.\d+){1,5}', line):
                    markdown_lines.append(f"## {line}")
                    continue

                # 2. 特殊块标记
                if line == "【关注点】":
                    markdown_lines.append("\n> **【关注点】**")
                    continue
                if line == "【示例】":
                    markdown_lines.append("\n> **【示例】**")
                    continue

                # 3. 表格识别（简单启发式）
                if is_table_line(line):
                    # 收集连续表格行
                    table_lines = [line]
                    # 注意：此处为简化，实际需跨行收集（本脚本按行处理）
                    markdown_lines.append(convert_to_markdown_table(table_lines))
                    continue

                # 4. 普通文本
                markdown_lines.append(line)

    # 写入 Markdown 文件
    with open(OUTPUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(markdown_lines))

    print(f"✅ Markdown 已生成: {OUTPUT_MD}")


def is_table_line(line: str) -> bool:
    """简单判断是否为表格行（含 | 且非章节/特殊块）"""
    return line.startswith("|") and "|" in line[1:]


def convert_to_markdown_table(table_lines):
    """将表格行转为标准 Markdown 表格"""
    if not table_lines:
        return ""
    # 确保有分隔行（|---|---|）
    first_row = table_lines[0]
    cols = first_row.count("|") - 1
    separator = "|" + "|".join(["---"] * cols) + "|"
    return "\n".join([first_row, separator] + table_lines[1:])


if __name__ == "__main__":
    main()