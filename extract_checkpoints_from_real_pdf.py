# -*- coding: utf-8 -*-
import re
import csv
import pdfplumber
from pathlib import Path
from typing import List, Dict, Tuple

def extract_sections_and_focus_with_real_tables(pdf_path: str) -> List[Dict]:
    """
    从真实 PDF 中提取章节、关注点、表格列名，并生成 Checkpoint 草稿
    """
    all_pages_text = []
    all_tables = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            # 提取文本（保留换行）
            text = page.extract_text(x_tolerance=1, y_tolerance=1)
            if text:
                all_pages_text.append((page_num, text))
            # 提取表格（保留原始结构）
            tables = page.extract_tables()
            for table in tables:
                if table and len(table) > 1:
                    all_tables.append({
                        "page": page_num,
                        "table": table
                    })

    # 合并全文（带页码标记）
    full_lines = []
    for page_num, text in all_pages_text:
        lines = text.split('\n')
        for line in lines:
            full_lines.append((page_num, line.strip()))

    # 步骤1: 识别章节标题
    section_pattern = r'^(\d+\.\d+\.P\.\d+(?:\.\d+)*)(?:\s+)(.+)$'
    sections = []
    current_section = None

    for page_num, line in full_lines:
        if not line:
            continue
        # 跳过孤立的 "2.3.P"
        if re.match(r'^\d+\.\d+\.P$', line):
            continue
        match = re.match(section_pattern, line)
        if match:
            sec_id = match.group(1).strip()
            sec_title = match.group(2).strip()
            current_section = {
                "id": sec_id,
                "title": sec_title,
                "start_page": page_num,
                "focus_lines": [],
                "tables": []
            }
            sections.append(current_section)
        elif current_section:
            if "【关注点】" in line:
                # 收集后续非章节行作为关注点
                idx = full_lines.index((page_num, line))
                for p, l in full_lines[idx+1:]:
                    if re.match(section_pattern, l) or l.startswith("2.3.P"):
                        break
                    if l and "【关注点】" not in l:
                        current_section["focus_lines"].append(l)
            # 暂不在此关联表格（下一步按页码匹配）

    # 步骤2: 为每个章节关联其页面范围内的表格
    for i, sec in enumerate(sections):
        start_page = sec["start_page"]
        end_page = sections[i+1]["start_page"] - 1 if i+1 < len(sections) else float('inf')
        sec_tables = [t for t in all_tables if start_page <= t["page"] <= end_page]
        sec["tables"] = sec_tables

    # 步骤3: 生成 Checkpoint
    checkpoints = []
    for sec in sections:
        sec_id = sec["id"]
        sec_title = sec["title"]

        # 3.1 语义类 Checkpoint（来自【关注点】）
        focus_text = " ".join(sec["focus_lines"]).strip()
        if focus_text:
            draft = focus_text
            if not draft.endswith("？"):
                if draft.endswith("。"):
                    draft = draft[:-1]
                draft = f"是否{draft}？"
            draft = re.sub(r'\s+', ' ', draft).strip()
            checkpoints.append({
                "section_id": sec_id,
                "section_title": sec_title,
                "type": "semantic",
                "source": "focus_point",
                "raw_text": focus_text,
                "checkpoint_draft": draft
            })

        # 3.2 表格类 Checkpoint（来自真实表格列名）
        for table_info in sec["tables"]:
            table = table_info["table"]
            header = table[0] if table else []
            # 清理列名（去除空值、合并跨列）
            clean_header = [str(h).strip() for h in header if h and str(h).strip()]
            if len(clean_header) >= 2:
                cols_str = "、".join([f"‘{col}’" for col in clean_header[:5]])  # 最多列5列
                table_draft = f"是否提供{sec_title}相关的结构化表格，且包含列：{cols_str}？"
                checkpoints.append({
                    "section_id": sec_id,
                    "section_title": sec_title,
                    "type": "table",
                    "source": "real_table",
                    "raw_text": f"表格列: {clean_header}",
                    "checkpoint_draft": table_draft
                })

    return checkpoints

def save_to_csv(checkpoints: List[Dict], output_csv: str):
    with open(output_csv, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=[
            "section_id", "section_title", "type", "source", "raw_text", "checkpoint_draft"
        ])
        writer.writeheader()
        writer.writerows(checkpoints)
    print(f"✅ 已生成 {len(checkpoints)} 条 Checkpoint，保存至: {output_csv}")

# ================== 使用 ==================
if __name__ == "__main__":
    pdf_file = "化学药品仿制药上市许可申请模块二药学资料撰写要求（制剂）（试行）.pdf"
    output_file = "checkpoints_from_real_pdf.csv"

    if not Path(pdf_file).exists():
        print(f"❌ 文件不存在: {pdf_file}")
    else:
        checkpoints = extract_sections_and_focus_with_real_tables(pdf_file)
        save_to_csv(checkpoints, output_file)