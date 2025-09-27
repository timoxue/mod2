# -*- coding: utf-8 -*-
import re
import csv
import pdfplumber
from pathlib import Path
from typing import List, Dict
from config import PDF_FILE, CSV_DIR


#PDF_FILE = "化学药品仿制药上市许可申请模块二药学资料撰写要求（制剂）（试行）.pdf"
OUTPUT_DIR = CSV_DIR

def extract_sections_and_content(pdf_path: str):
    """通用提取器：章节、关注点、表格（按页码归属）"""
    with pdfplumber.open(pdf_path) as pdf:
        pages_text = [(i+1, page.extract_text(x_tolerance=1, y_tolerance=1) or "") for i, page in enumerate(pdf.pages)]
        pages_tables = [(i+1, page.extract_tables()) for i, page in enumerate(pdf.pages)]
        _, text = pages_text[6]
        print(text)
    # 识别章节（通用正则）
    section_pattern = r'^(\d+\.\d+\.P\.\d+(?:\.\d+)*)(?:\s+)(.+).*'

    # 合并全文行（带页码）并拆分出4级标题及正文lines
    all_lines = []
    daopai_lines = []
    chunk = []
    sec_id = "UKN"
    level = 0
    title = 'UKN'
    parent_sid = 'UKN'
    title_list = ''
    idx_line = 0
    sid_map = {}
    title_map = {}
    for page_num, text in pages_text:
        for line in text.split('\n'):
            line = line.strip()
            if line:
                all_lines.append(line)
                match = re.match(section_pattern, line)
                if match and page_num > 2:
                    sec_id = match.group(1).strip()
                    title = match.group(2).strip()
                    level = (len(sec_id)+1) / 2
                    if level == 4:
                        title_list =''
                    title_list = title_list.join( sec_id +';')
            #包含page_num的列不保存
            if not line.isdigit():
                chunk.append((title_list, line))


    sections = []
    sec_relations = []
    current = None

    for page_num, line in all_lines:
        if re.match(r'^\d+\.\d+\.P$', line):  # 跳过 "2.3.P"
            continue
        match = re.match(section_pattern, line)
        # if line.startswith("2.3.P.2.1.1"):
        #     print(line)
        if match:
            sec_id = match.group(1).strip()
            title = match.group(2).strip()
            current = {"id": sec_id, "title": title, "start_page": page_num, "focus": "", "tables": []}
            # 检查是否已有相同 id 的章节
            existing = None
            for i, sec in enumerate(sections):
                if sec["id"] == current["id"]:
                    existing = i
                    break

            if existing is not None:
                # 已存在相同 id 的章节
                existing_sec = sections[existing]
                # 判断哪条标题更完整（不含 '....'）
                if "...." in existing_sec["title"] and "...." not in current["title"]:
                    # 旧标题含 '....'，新标题完整 → 替换
                    sections[existing] = current
                    current = None
                elif "...." in current["title"] and "...." not in existing_sec["title"]:
                    # 新标题含 '....'，旧标题完整 → 丢弃新记录，不做 append
                    current = None
                else:
                    # 两者都含或都不含 '....'，保留第一个（或可合并，此处保留原逻辑）
                    current = None

            # 只有 current 有效时才 append
            if current is not None:
                sections.append(current)
        elif current and "【关注点】" in line:
            # 收集关注点（直到下一章节）
            idx = all_lines.index((page_num, line))
            focus = ""
            for p, l in all_lines[idx+1:]:
                if re.match(section_pattern, l) or l.startswith("2.3.P"):
                    break
                if l and "【关注点】" not in l:
                    focus += l + " "
            current["focus"] = re.sub(r'\s+', ' ', focus).strip()

    # 关联表格（按页码区间）
    for i, sec in enumerate(sections):
        start = sec["start_page"]
        end = sections[i+1]["start_page"] - 1 if i+1 < len(sections) else float('inf')
        tables_in_section = []
        for page_num, tables in pages_tables:
            if start <= page_num <= end:
                for tbl in tables:
                    if tbl and len(tbl) > 1:
                        tables_in_section.append(tbl)
        sec["tables"] = tables_in_section

    return sections




def generate_csvs(sections: List[Dict], output_dir: str):
    """生成 regulations.csv, sections.csv, requirements.csv, checkpoints.csv"""
    Path(output_dir).mkdir(exist_ok=True)

    # 1. regulations.csv
    with open(f"{output_dir}/regulations.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, ["id", "name", "authority", "publish_date"])
        writer.writeheader()
        writer.writerow({
            "id": "NMPA_MODULE2_2025",
            "name": "化学药品仿制药上市许可申请模块二药学资料撰写要求（制剂）（试行）",
            "authority": "NMPA",
            "publish_date": "2025-08"
        })

    # 2. sections.csv
    with open(f"{output_dir}/sections.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, ["id", "regulation_id", "title"])
        writer.writeheader()
        for sec in sections:
            writer.writerow({
                "id": f"SEC_{sec['id'].replace('.', '_')}",
                "regulation_id": "NMPA_MODULE2_2025",
                "title": f"{sec['id']} {sec['title']}"
            })

    # 3. requirements.csv & 4. checkpoints.csv
    requirements = []
    checkpoints = []

    for sec in sections:
        sec_id_clean = sec["id"].replace(".", "_")
        sec_id_neo4j = f"SEC_{sec_id_clean}"
        focus = sec["focus"]
        tables = sec["tables"]

        # === 3.1 语义类：从【关注点】提炼 Requirement ===
        if focus:
            # 提炼要求：将“关注...” → “应关注...” / “需评估...”
            req_text = focus
            if not req_text.startswith(("应", "需", "要", "必须", "建议")):
                if "关注" in req_text[:10]:
                    req_text = "应" + req_text
                else:
                    req_text = "需" + req_text
            req_id = f"REQ_{sec_id_clean}_FOCUS"
            requirements.append({"id": req_id, "section_id": sec_id_neo4j, "text": req_text})

            # 对应 Checkpoint
            draft = f"是否{focus.rstrip('。')}？" if not focus.endswith("？") else focus
            checkpoints.append({
                "id": f"CHK_{sec_id_clean}_FOCUS",
                "requirement_id": req_id,
                "text": draft,
                "ctd_location": sec["id"],
                "severity": "High"
            })

        # === 3.2 表格类：每个表格独立 Requirement ===
        for tbl_idx, table in enumerate(tables):
            if len(table) < 2:
                continue
            header = table[0]
            clean_header = [str(h).strip() for h in header if h and str(h).strip()]
            if len(clean_header) < 2:
                continue

            # 表格类 Requirement：明确表达“需提供结构化表格”
            req_id_table = f"REQ_{sec_id_clean}_TABLE_{tbl_idx}"
            req_text_table = f"需提供{sec['title']}相关的结构化表格，包含明确的列定义。"
            requirements.append({"id": req_id_table, "section_id": sec_id_neo4j, "text": req_text_table})

            # 对应 Checkpoint
            cols_str = "、".join([f"‘{col}’" for col in clean_header[:5]])
            table_draft = f"是否提供{sec['title']}相关的结构化表格，且包含列：{cols_str}？"
            checkpoints.append({
                "id": f"CHK_{sec_id_clean}_TABLE_{tbl_idx}",
                "requirement_id": req_id_table,
                "text": table_draft,
                "ctd_location": sec["id"],
                "severity": "Medium"
            })

    # 写入 requirements.csv
    with open(f"{output_dir}/requirements.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, ["id", "section_id", "text"])
        writer.writeheader()
        writer.writerows(requirements)

    # 写入 checkpoints.csv
    with open(f"{output_dir}/checkpoints.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, ["id", "requirement_id", "text", "ctd_location", "severity"])
        writer.writeheader()
        writer.writerows(checkpoints)

    print(f"✅ 已生成 4 个 CSV 文件，保存至: {output_dir}/")
    print(f"   - regulations.csv: 1 条")
    print(f"   - sections.csv: {len(sections)} 条")
    print(f"   - requirements.csv: {len(requirements)} 条")
    print(f"   - checkpoints.csv: {len(checkpoints)} 条")

# ================== 主程序 ==================
if __name__ == "__main__":
    if not Path(PDF_FILE).exists():
        raise FileNotFoundError(f"请确保 PDF 文件存在: {PDF_FILE}")

    print("🔍 正在解析 PDF，提取章节、关注点和表格...")
    sections = extract_sections_and_content(PDF_FILE)
    generate_csvs(sections, OUTPUT_DIR)