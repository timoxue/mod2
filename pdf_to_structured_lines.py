# -*- coding: utf-8 -*-
"""
增强版 PDF 结构化解析脚本
- 每行输出 JSON 对象
- section_path 包含主章节 + 子条款（一、1、①、(1)）
- 表格连续识别（整张表共享 block_id）
- 【关注点】/【示例】/表格作为特殊块（含标题行）
"""
import re
import json
from pathlib import Path
import pdfplumber

PDF_FILE = Path("化学药品仿制药上市许可申请模块二药学资料撰写要求（制剂）（试行）.pdf")
OUTPUT_JSON = Path("structured_lines.json")


def main():
    if not PDF_FILE.exists():
        raise FileNotFoundError(f"❌ PDF 文件不存在: {PDF_FILE}")

    print("🔍 正在解析 PDF...")
    lines_data = parse_pdf_to_structured_lines(PDF_FILE)

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(lines_data, f, ensure_ascii=False, indent=2)

    print(f"✅ 结构化 JSON 已保存至: {OUTPUT_JSON}")


def parse_pdf_to_structured_lines(pdf_path: Path):
    """解析 PDF 每行，输出结构化 JSON 列表"""
    with pdfplumber.open(pdf_path) as pdf:
        all_raw_lines = []
        for page in pdf.pages:
            text = page.extract_text(x_tolerance=1, y_tolerance=1)
            if text:
                all_raw_lines.extend(text.split('\n'))

    section_stack = []          # 当前章节路径栈（含子条款）
    block_type = None           # 当前块类型：concern / example / table
    block_id = None             # 当前块 ID
    block_counter = {}          # 块计数器：{(section_id, type): count}
    result = []

    i = 0
    while i < len(all_raw_lines):
        raw_line = all_raw_lines[i]
        line = raw_line.strip()
        print()
        current_block_type = None
        current_block_id = None

        # ========== 1. 主章节识别（2.3.P.x.x.x） ==========
        if re.fullmatch(r'2\.3\.P(\.\d+){1,5}', line):
            sec_id = line
            # 弹出非祖先节点
            while section_stack:
                top = section_stack[-1]
                if is_ancestor(top, sec_id):
                    break
                section_stack.pop()
            section_stack.append(sec_id)
            block_type = None
            block_id = None

        # ========== 2. 子条款识别（作为章节节点） ==========
        elif section_stack:
            parent_id = section_stack[-1]
            new_sub_id = None

            # (1) 中文数字：一、二、...
            match = re.match(r'^([一二三四五六七八九十]+)、', line)
            if match:
                num = match.group(1)
                new_sub_id = f"{parent_id}.{num}"
            # (2) 阿拉伯数字：1、2、...
            elif re.match(r'^\d+、', line):
                num = re.match(r'^(\d+)、', line).group(1)
                new_sub_id = f"{parent_id}.{num}"
            # (3) 圈码：①②...
            elif re.match(r'^[①②③④⑤⑥⑦⑧⑨⑩]', line):
                num = line[0]
                new_sub_id = f"{parent_id}.{num}"
            # (4) 括号数字：（1）（2）...
            elif re.match(r'^（(\d+)）', line):
                num = re.match(r'^（(\d+)）', line).group(1)
                new_sub_id = f"{parent_id}.({num})"

            if new_sub_id:
                # 压入子条款节点
                section_stack.append(new_sub_id)
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


def is_ancestor(parent: str, child: str) -> bool:
    """判断 parent 是否是 child 的祖先章节（支持子条款）"""
    if child.startswith(parent + "."):
        suffix = child[len(parent)+1:]
        # 允许子条款后缀：一、1、①、(1) 
        return bool(re.match(r'^[一二三四五六七八九十\d①②③④⑤⑥⑦⑧⑨⑩(]\d*\)?$', suffix))
    return False


def is_table_line(line: str) -> bool:
    """判断是否为表格行（以 | 开头，且含至少两个 |）"""
    return line.startswith("|") and line.count("|") >= 2


def generate_block_id(section_stack, block_type, counter):
    """生成块 ID：{type}_{section_id}_{index}"""
    if not section_stack:
        return f"{block_type}_global_{counter.get(('global', block_type), 0) + 1}"
    sec_id = section_stack[-1].replace(".", "_")
    key = (sec_id, block_type)
    counter[key] = counter.get(key, 0) + 1
    return f"{block_type}_{sec_id}_{counter[key]}"


if __name__ == "__main__":
    main()