# -*- coding: utf-8 -*-
import json
import re
from typing import List, Dict, Any
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from neo4j import GraphDatabase
import os

# ================== 配置 ==================
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "password"
os.environ['DASHSCOPE_API_KEY'] = 'sk-57056cdaa1ec49c883e585d7ce1ea3d5'

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

if not DASHSCOPE_API_KEY:
    raise ValueError("请设置环境变量 DASHSCOPE_API_KEY")

# ================== Neo4j 工具 ==================
driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

def clear_existing_review_points():
    """删除 Neo4j 中所有已存在的 ReviewPoint 节点"""
    print("🗑️  正在清理旧的 ReviewPoint 节点...")
    with driver.session() as session:
        result = session.run("MATCH (r:ReviewPoint) DETACH DELETE r")
        count = result.consume().counters.nodes_deleted
        print(f"✅ 已删除 {count} 个旧的 ReviewPoint 节点")

def clean_review_points(points: List[Dict]) -> List[Dict]:
    original_count = len(points)

    """清洗审核点列表，确保数据干净、合规"""
    cleaned = []
    seen = set()  # 用于去重：(question, section_id)

    for p in points:
        # 1. 必填字段检查
        required_fields = ["type", "question", "evidence", "section_id"]
        if not all(k in p and p[k] for k in required_fields):
            continue

        # 2. question 必须以“是否”开头
        q = p["question"].strip()
        if not q.startswith("是否"):
            continue

        # 3. evidence 长度合理（5~100 字符）
        e = p["evidence"].strip()
        if len(e) < 5 or len(e) > 100:
            continue

        # 4. type 必须是 required/recommended
        if p["type"] not in ["required", "recommended"]:
            continue

        # 5. 去重：相同问题 + 相同章节
        key = (q, p["section_id"])
        if key in seen:
            continue
        seen.add(key)

        # 6. 标准化字段
        cleaned.append({
            "review_id": p["review_id"],
            "block_id": p.get("block_id"),
            "section_id": p["section_id"],
            "type": p["type"],
            "question": q,
            "evidence": e
        })
    print(f"🧹 清洗审核点: {original_count} → {len(cleaned)} 条")
    return cleaned


def get_block_content(block_id: str) -> str:
    query = """
    MATCH (l:Line {block_id: $block_id})
    WITH l
    ORDER BY l.line_number
    RETURN collect(l.text) AS lines
    """
    with driver.session() as session:
        result = session.run(query, block_id=block_id).single()
        return "\n".join(result["lines"]) if result else ""

def get_section_content(section_id: str) -> str:
    query = """
    MATCH (l:Line)
    WHERE ANY(p IN l.section_path WHERE p STARTS WITH $section_id)
      AND l.block_id IS NOT NULL
    WITH l
    ORDER BY l.line_number
    RETURN collect(l.text) AS lines
    """
    with driver.session() as session:
        result = session.run(query, section_id=section_id).single()
        return "\n".join(result["lines"]) if result else ""

# ================== 动态 Prompt 模板 ==================
def get_system_prompt(block_type: str, section_id: str) -> str:
    if block_type == "concern":
        return f"""
你是一名资深药品注册审评专家，请根据以下【关注点】内容，生成可验证的审核问题。
要求：
1. 聚焦技术风险：如原料药特性对制剂性能的影响、限度制定依据等
2. 问题必须以“是否……？”开头
3. 提供原文关键证据
4. 如果出现“如",“比如”等举例的词汇，是表示举例，你要把内在审核逻辑抽取出来，而不是把举例作为审核点
5. 输出 JSON：{{"review_points": [{{"type": "required", "question": "...", "evidence": "...", "source_block_id": "...", "source_section_id": "{section_id}"}}]}}
"""
    elif block_type == "table":
        return f"""
你是一名药品注册数据审核专家，请根据以下表格内容，检查表格完整性与合规性。
要求：
1. 检查是否有表格名称（如“原料药信息表”）
2. 检查列名是否齐全（如“名称、生产企业、执行标准、登记号”）
3. 检查数据是否缺失或逻辑矛盾
4. 问题以“是否提供包含‘A、B、C’列的表格？”或“表格中是否缺失...？”开头
5. 输出 JSON：{{"review_points": [{{"type": "required", "question": "...", "evidence": "...", "source_block_id": "...", "source_section_id": "{section_id}"}}]}}
"""
    elif block_type == "example":
        return f"""
你是一名药品注册文档审核专家，请根据以下【示例】内容，生成检查申报资料是否符合示例要求的审核点。
要求：
1. 对比申报内容是否包含示例中的关键要素（如研究项目、参数、格式）
2. 检查逻辑结构、术语、单位是否一致
3. 问题以“是否参照示例提供……？”开头
4. 如果出现“如",“比如”等举例的词汇，是表示举例，你要把内在审核逻辑抽取出来，而不是把举例作为审核点
5. 输出 JSON：{{"review_points": [{{"type": "recommended", "question": "...", "evidence": "...", "source_block_id": "...", "source_section_id": "{section_id}"}}]}}
"""
    else:  # section
        return f"""
你是一名药品注册高级审评员，请根据以下章节（{section_id}）的全部技术要求，生成综合审核清单。
要求：
1. 覆盖所有关键要素：处方、质量标准、方法验证、稳定性等
2. 区分“必须项”（required）和“建议项”（recommended）
3. 问题以“是否……？”开头
4. 如果出现“如",“比如”等举例的词汇，是表示举例，你要把内在审核逻辑抽取出来，而不是把举例作为审核点
5. 输出 JSON：{{"review_points": [{{"type": "...", "question": "...", "evidence": "...", "source_block_id": null, "source_section_id": "{section_id}"}}]}}
"""

# ================== 审核点生成 ==================
def generate_review_points_for_block(block_id: str, section_id: str, block_type: str) -> List[Dict]:
    content = get_block_content(block_id)
    if not content.strip():
        return []

    llm = ChatOpenAI(
        model="qwen-max",
        openai_api_key=DASHSCOPE_API_KEY,
        openai_api_base="https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    
    system_prompt = get_system_prompt(block_type, section_id)
    agent = create_react_agent(llm, tools=[], prompt=SystemMessage(content=system_prompt))
    
    input_text = f"根据以下内容生成审核点：\n{content}"
    response = agent.invoke({"messages": [("user", input_text)]})
    return parse_agent_output(response["messages"][-1].content, block_id, section_id)

def generate_review_points_for_section(section_id: str) -> List[Dict]:
    content = get_section_content(section_id)
    if not content.strip():
        return []

    llm = ChatOpenAI(
        model="qwen-max",
        openai_api_key=DASHSCOPE_API_KEY,
        openai_api_base="https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    
    system_prompt = get_system_prompt("section", section_id)
    agent = create_react_agent(llm, tools=[], prompt=SystemMessage(content=system_prompt))
    
    input_text = f"根据以下章节内容生成审核点：\n{content}"
    response = agent.invoke({"messages": [("user", input_text)]})
    return parse_agent_output(response["messages"][-1].content, None, section_id)

def parse_agent_output(raw_output: str, block_id: str, section_id: str) -> List[Dict]:
    try:
        json_match = re.search(r'\{.*\}', raw_output, re.DOTALL)
        if not json_match:
            return []
        data = json.loads(json_match.group(0))
        points = []
        for item in data.get("review_points", []):
            if all(k in item for k in ["type", "question", "evidence"]):
                points.append({
                    "review_id": f"RP_{block_id or section_id}_{hash(item['question']) % 10000}",
                    "block_id": block_id,
                    "section_id": section_id,
                    "type": item["type"],
                    "question": item["question"],
                    "evidence": item["evidence"]
                })
        return points
    except Exception as e:
        print(f"⚠️ JSON 解析失败: {e}")
        return []

# ================== 保存到 Neo4j ==================
def save_review_points(points: List[Dict]):
    query = """
    CREATE (:ReviewPoint {
      review_id: $review_id,
      block_id: $block_id,
      section_id: $section_id,
      type: $type,
      question: $question,
      evidence: $evidence,
      created_at: timestamp()
    })
    """
    with driver.session() as session:
        for p in points:
            session.run(query, p)

# ================== 主流程 ==================
def main():
    # 🔥 新增：清理旧数据
    clear_existing_review_points()
    # 1. 生成 block 审核点
    block_query = """
    MATCH (l:Line)
    WHERE l.block_id IS NOT NULL AND l.block_type IN ['concern', 'table', 'example']
    RETURN DISTINCT l.block_id, l.parent_section, l.block_type
    """
    with driver.session() as session:
        blocks = list(session.run(block_query))
        for record in blocks:
            block_id = record["l.block_id"]
            section_id = record["l.parent_section"]
            block_type = record["l.block_type"]
            print(f"🔍 生成 {block_type} block {block_id} 的审核点...")
            points = generate_review_points_for_block(block_id, section_id, block_type)
            points = clean_review_points(points)  # ← 新增清洗

            save_review_points(points)
    
    # 2. 生成 section 审核点
    section_query = """
    MATCH (l:Line)
    WHERE l.section_path IS NOT NULL
    UNWIND l.section_path AS path
    WITH path WHERE path STARTS WITH '2.3.P.'
    RETURN DISTINCT path AS section_id
    ORDER BY section_id
    """
    # with driver.session() as session:
    #     sections = [r["section_id"] for r in session.run(section_query)]
    #     for sec_id in sections:
    #         print(f"🔍 生成 section {sec_id} 的审核点...")
    #         points = generate_review_points_for_section(sec_id)
    #         points = clean_review_points(points)
    #         save_review_points(points)
    
    # print("✅ 审核点生成完成！")

if __name__ == "__main__":
    main()