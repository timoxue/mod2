# -*- coding: utf-8 -*-
"""
将 PDF 每行文本结构化为 JSON，包含：
- 行号
- 原始文本
- 所属章节路径（section_path）
- 特殊块类型（【关注点】/【示例】/表格）
- 特殊块 ID（同一块内共享）
- 子条款编号（一、1、①、（1）等）
"""
import re
import json
from pathlib import Path
import pdfplumber

PDF_FILE = Path("化学药品仿制药上市许可申请模块二药学资料撰写要求（制剂）（试行）.pdf")
OUTPUT_JSON = Path("lines_structured.json")


def main():
    if not PDF_FILE.exists():
        raise FileNotFoundError(f"❌ PDF 文件不存在: {PDF_FILE}")

    print("🔍 正在解析 PDF...")
    lines_data = parse_pdf_lines_with_context(PDF_FILE)

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(lines_data, f, ensure_ascii=False, indent=2)

    print(f"✅ 结构化 JSON 已保存至: {OUTPUT_JSON}")


def parse_pdf_lines_with_context(pdf_path: Path):
    with pdfplumber.open(pdf_path) as pdf:
        all_raw_lines = []
        for page in pdf.pages:
            text = page.extract_text(x_tolerance=1, y_tolerance=1)
            if text:
                all_raw_lines.extend(text.split('\n'))

    section_stack = []
    block_type = None
    block_id = None
    block_counter = {}
    result = []

    i = 0
    while i < len(all_raw_lines):
        raw_line = all_raw_lines[i]
        line = raw_line.strip()
        print(line)
        current_block_type = None
        current_block_id = None

        # ========== 1. 主章节识别（2.3.P.x.x.x） ==========
        if re.fullmatch(r'2\.3\.P(\.\d+){1,5}', line):
            sec_id = line
            # 更新章节栈（弹出非祖先）
            while section_stack:
                top = section_stack[-1]
                if is_parent_section(top, sec_id):
                    break
                section_stack.pop()
            section_stack.append(sec_id)
            block_type = None
            block_id = None

        # ========== 2. 子条款识别（作为章节） ==========
        elif section_stack:
            current_parent = section_stack[-1]
            sub_id = None

            # （1）中文数字：一、二、...
            if re.match(r'^[一二三四五六七八九十]+、', line):
                num = re.match(r'^([一二三四五六七八九十]+)、', line).group(1)
                sub_id = f"{current_parent}.{num}"
            # （2）阿拉伯数字：1、2、...
            elif re.match(r'^\d+、', line):
                num = re.match(r'^(\d+)、', line).group(1)
                sub_id = f"{current_parent}.{num}"
            # （3）圈码：①②...
            elif re.match(r'^[①②③④⑤⑥⑦⑧⑨⑩]', line):
                num = line[0]
                sub_id = f"{current_parent}.{num}"
            # （4）括号数字：（1）（2）...
            elif re.match(r'^（\d+）', line):
                num = re.match(r'^（(\d+)）', line).group(1)
                sub_id = f"{current_parent}.({num})"

            if sub_id:
                # 子条款作为新章节压栈
                section_stack.append(sub_id)
                block_type = None
                block_id = None

        # ========== 3. 特殊块识别 ==========
        if line == "【关注点】":
            block_type = "concern"
            block_id = generate_block_id(section_stack, block_type, block_counter)
        elif line == "【示例】":
            block_type = "example"
            block_id = generate_block_id(section_stack, block_type, block_counter)
        elif is_table_line(line):
            if block_type != "table":
                block_type = "table"
                block_id = generate_block_id(section_stack, block_type, block_counter)
            current_block_type = block_type
            current_block_id = block_id
        else:
            # 非表格行：退出表格块
            if block_type == "table":
                block_type = None
                block_id = None
            current_block_type = block_type
            current_block_id = block_id

        # ========== 4. 构建行对象 ==========
        row = {
            "line_number": i + 1,
            "text": raw_line,
            "section_path": list(section_stack),
            "block_type": current_block_type,
            "block_id": current_block_id
        }
        result.append(row)

        i += 1

    return result


def is_section_id(line: str) -> bool:
    """判断是否为章节编号（2.3.P.x 到 2.3.P.x.x.x.x）"""
    section_pattern = r'^(\d+\.\d+\.P\.\d+(?:\.\d+)*)(?:\s+)(.+).*'
    return bool(re.fullmatch(section_pattern, line)) and  '......' not in line


def is_parent_section(parent: str, child: str) -> bool:
    """判断 parent 是否是 child 的父章节（支持子条款）"""
    if child.startswith(parent + "."):
        suffix = child[len(parent)+1:]
        # 允许子条款如 "一", "1", "①", "(1)"
        return bool(re.match(r'^[一二三四五六七八九十\d①②③④⑤⑥⑦⑧⑨⑩(]\d*\)?$', suffix))
    return False

def is_table_line(line: str) -> bool:
    """判断是否为表格行（支持连续多行）"""
    return line.startswith("|") and "|" in line[1:]

def is_table_start(lines, idx):
    """判断当前行是否为表格起始行"""
    if idx + 1 >= len(lines):
        return False
    current = lines[idx].strip()
    next_line = lines[idx+1].strip()
    return (current.startswith("|") and 
            "---" in next_line and 
            next_line.startswith("|"))

def generate_block_id(section_stack, block_type, counter):
    """生成特殊块 ID：{type}_{section_id}_{index}"""
    if not section_stack:
        return None
    sec_id = section_stack[-1]
    key = (sec_id, block_type)
    counter[key] = counter.get(key, 0) + 1
    return f"{block_type}_{sec_id}_{counter[key]}"


def extract_sub_clause(line: str) -> str:
    """提取子条款编号（一、1、①、（1）等）"""
    patterns = [
        r'^([一二三四五六七八九十]+)、',
        r'^(\d+)、',
        r'^([①②③④⑤⑥⑦⑧⑨⑩])',
        r'^（(\d+)）'
    ]
    for pattern in patterns:
        match = re.match(pattern, line)
        if match:
            return match.group(1)
    return None


if __name__ == "__main__":
    main()