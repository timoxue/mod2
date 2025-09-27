# -*- coding: utf-8 -*-
"""
递归解析《模块二撰写要求》PDF，输出结构化 JSON
支持 L1-L6 层级、特殊块识别、内部引用提取、子条款识别
输出格式符合指定 schema
"""
import re
import json
from pathlib import Path
import pdfplumber

PDF_FILE = Path("化学药品仿制药上市许可申请模块二药学资料撰写要求（制剂）（试行）.pdf")
OUTPUT_JSON = Path("module2_structured.json")


def main():
    if not PDF_FILE.exists():
        raise FileNotFoundError(f"❌ PDF 文件不存在: {PDF_FILE}")

    print("🔍 正在解析 PDF...")
    sections = parse_pdf_to_sections(PDF_FILE)
    tree = build_section_tree(sections)

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(tree, f, ensure_ascii=False, indent=2)

    print(f"✅ 结构化 JSON 已保存至: {OUTPUT_JSON}")


def parse_pdf_to_sections(pdf_path: Path):
    """解析 PDF，返回扁平化章节列表"""
    with pdfplumber.open(pdf_path) as pdf:
        pages = []
        for i, page in enumerate(pdf.pages):
            text = page.extract_text(x_tolerance=1, y_tolerance=1) or ""
            tables = page.extract_tables() or []
            pages.append((i+1, text, tables))

    all_lines = []
    for page_num, text, _ in pages:
        for line in text.split('\n'):
            line = line.strip()
            if line:
                all_lines.append((page_num, line))

    # 提取章节编号行（支持 L3-L6）
    section_id_pattern = r'^(\d+\.\d+\.P\.\d+(?:\.\d+)*)(?:\s+)(.+).*'
    section_headers = []
    for i, (page_num, line) in enumerate(all_lines):
        match= re.match(section_id_pattern, line)
        if match:
            sec_id = match.group(1).strip()
            title = match.group(2).strip()

            title = "..."
            if i + 1 < len(all_lines):
                next_line = all_lines[i+1][1]
                if (not re.match(section_id_pattern, next_line) 
                    and not re.match(r'^2\.3\.P$', next_line)
                    and not next_line.isdigit()):
                    title = next_line
            section_headers.append((i, page_num, line, title))

    sections = []
    for idx, (start_idx, start_page, sec_id, title) in enumerate(section_headers):
        end_idx = section_headers[idx+1][0] if idx+1 < len(section_headers) else len(all_lines)
        end_page = section_headers[idx+1][1] if idx+1 < len(section_headers) else float('inf')

        # 提取正文（不含子章节）
        text_lines = []
        for j in range(start_idx + 1, end_idx):
            _, line = all_lines[j]
            if re.match(section_id_pattern, line):
                break
            text_lines.append(line)
        raw_text = "\n".join(text_lines).strip()

        # 提取表格（按页码）
        tables = []
        for page_num, _, page_tables in pages:
            if start_page <= page_num <= end_page:
                for tbl in page_tables:
                    if tbl and len(tbl) > 1:
                        tables.append(tbl)

        sections.append({
            "id": sec_id,
            "title": title,
            "raw_text": raw_text,
            "tables": tables,
            "start_page": start_page,
            "end_page": end_page
        })

    return sections


def build_section_tree(flat_sections):
    """构建递归章节树"""
    # 按 id 排序（确保父节点在前）
    flat_sections.sort(key=lambda x: x["id"])
    
    root = {"children": []}
    node_map = {}

    for sec in flat_sections:
        level = len(sec["id"].split('.'))
        content = extract_main_content(sec["raw_text"])
        has_table = len(sec["tables"]) > 0
        has_example = "【示例】" in sec["raw_text"]
        has_concern = "【关注点】" in sec["raw_text"]
        references = extract_references(sec["raw_text"])

        node = {
            "id": sec["id"],
            "title": sec["title"],
            "level": level,
            "type": "section",
            "content": content,
            "has_table": has_table,
            "has_example": has_example,
            "has_concern": has_concern,
            "references": references,
            "children": []
        }
        node_map[sec["id"]] = node

        # 找父节点
        parent_id = find_parent_id(sec["id"])
        if parent_id and parent_id in node_map:
            node_map[parent_id]["children"].append(node)
        else:
            root["children"].append(node)

    return root["children"]


def extract_main_content(text: str) -> str:
    """提取正文（移除【关注点】【示例】及之后内容）"""
    for marker in ["【关注点】", "【示例】"]:
        if marker in text:
            text = text.split(marker)[0].strip()
    return text


def extract_references(text: str) -> list:
    """提取内部引用（如“参照 2.3.P.5.3”）"""
    refs = re.findall(r'参照\s*(2\.3\.P\.\d+(?:\.\d+)*)', text)
    return sorted(list(set(refs)))


def find_parent_id(sec_id: str) -> str:
    """根据章节ID找父ID（如 2.3.P.2.1.1 → 2.3.P.2.1）"""
    parts = sec_id.split('.')
    if len(parts) > 4:  # 2.3.P.x 为L3，x.x为L4+
        return '.'.join(parts[:-1])
    return ""


if __name__ == "__main__":
    main()