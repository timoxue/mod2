# -*- coding: utf-8 -*-
import re
import json
from pathlib import Path

INPUT_FILE = "content.txt"
OUTPUT_FILE = "structured_lines.json"

def main():
    input_path = Path(INPUT_FILE)
    if not input_path.exists():
        raise FileNotFoundError(f"❌ 文件不存在: {INPUT_FILE}")

    with open(input_path, "r", encoding="utf-8") as f:
        raw_lines = f.readlines()

    result = []
    section_stack = []
    block_type = None
    block_id = None
    block_counter = {}
    in_table = False
    current_table_id = None

    for line_num, raw_line in enumerate(raw_lines, start=1):
        line = raw_line.strip()
        if line.rstrip('\n').isdigit():
            continue
        current_block_type = None
        current_block_id = None

        # ========== 1. 精确识别章节编号行（如 "2.3.P.2.1.1原料药"） ==========
        # 匹配以 2.3.P.x.x.x 开头的行（允许后面紧跟中文）
        match = re.match(r'^(2\.3\.P(\.\d+){1,5})(.*)$', line)
        if match:
            sec_id = match.group(1)
            # 更新章节栈
            while section_stack:
                top = section_stack[-1]
                if is_ancestor(top, sec_id):
                    break
                section_stack.pop()
            section_stack.append(sec_id)
            block_type = None
            block_id = None
            in_table = False
            current_table_id = None

        # ========== 2. 子条款识别（作为章节节点） ==========
        elif section_stack:
            parent = section_stack[-1]
            new_sub_id = None

            # (1) 中文数字：一、二、...
            match = re.match(r'^([一二三四五六七八九十]+)、', line)
            if match:
                num = match.group(1)
                new_sub_id = f"{parent}.{num}"
            # (2) 阿拉伯数字：1、2、...
            elif re.match(r'^\d+、', line):
                num = re.match(r'^(\d+)、', line).group(1)
                new_sub_id = f"{parent}.{num}"
            # (3) 圈码：①②...
            elif re.match(r'^[①②③④⑤⑥⑦⑧⑨⑩]', line):
                num = line[0]
                new_sub_id = f"{parent}.{num}"
            # (4) 括号数字：（1）（2）...
            elif re.match(r'^（(\d+)）', line):
                num = re.match(r'^（(\d+)）', line).group(1)
                new_sub_id = f"{parent}.({num})"

            if new_sub_id:
                section_stack.append(new_sub_id)
                block_type = None
                block_id = None
                in_table = False
                current_table_id = None

        # ========== 3. 特殊块识别 ==========
        if line == "<<TABLE_START>>":
            in_table = True
            block_type = "table"
            # 使用 parent_section（即当前章节ID）生成 block_id
            parent_sec = section_stack[-1] if section_stack else "global"
            current_table_id = generate_block_id(parent_sec, "table", block_counter)
            continue
        elif line == "<<TABLE_END>>":
            in_table = False
            block_type = None
            block_id = None
            current_table_id = None
            continue
        elif line == "【关注点】":
            parent_sec = section_stack[-1] if section_stack else "global"
            block_type = "concern"
            block_id = generate_block_id(parent_sec, "concern", block_counter)
        elif line == "【示例】":
            parent_sec = section_stack[-1] if section_stack else "global"
            block_type = "example"
            block_id = generate_block_id(parent_sec, "example", block_counter)
        else:
            if in_table:
                current_block_type = "table"
                current_block_id = current_table_id
            else:
                current_block_type = block_type
                current_block_id = block_id

        # ========== 4. 构建行对象 ==========
        parent_section = section_stack[-1] if section_stack else None
        row = {
            "line_number": line_num,
            "text": raw_line.rstrip('\n'),
            "section_path": list(section_stack),
            "parent_section": parent_section,  # ← 新增字段
            "block_type": current_block_type,
            "block_id": current_block_id
        }
        result.append(row)

    # 保存 JSON
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"✅ 已生成结构化 JSON 文件: {OUTPUT_FILE}")


def is_ancestor(parent: str, child: str) -> bool:
    """判断 parent 是否是 child 的祖先章节"""
    if child.startswith(parent + "."):
        suffix = child[len(parent)+1:]
        return bool(re.match(r'^[一二三四五六七八九十\d①②③④⑤⑥⑦⑧⑨⑩(]\d*\)?$', suffix))
    return child == parent  # 同级章节不弹出


def generate_block_id(parent_section: str, block_type: str, counter: dict):
    """基于 parent_section 生成 block_id"""
    sec_id_clean = parent_section.replace(".", "_")
    key = (sec_id_clean, block_type)
    counter[key] = counter.get(key, 0) + 1
    return f"{block_type}_{sec_id_clean}_{counter[key]}"


if __name__ == "__main__":
    main()