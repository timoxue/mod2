# -*- coding: utf-8 -*-
import json
import re
import time
from neo4j import GraphDatabase
from dashscope import Generation
import os
import dashscope

# ================== 配置 ==================
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "password"
os.environ['DASHSCOPE_API_KEY'] = 'sk-57056cdaa1ec49c883e585d7ce1ea3d5'

# 设置 DashScope API Key（从环境变量读取）
dashscope.api_key = os.getenv("DASHSCOPE_API_KEY")
if not dashscope.api_key:
    raise ValueError("请设置环境变量 DASHSCOPE_API_KEY")

SELECTED_MODEL = "qwen-max"  # 可选: qwen-max, deepseek-7b-chat, doubao-lite-2405

# ================== Prompt 模板（强制 JSON 输出） ==================
PROMPTS = {
    "concern": """
你是一名资深药品注册审评专家，请根据以下【关注点】内容，生成 3–5 条审核点。
要求：
1. 每条必须标注类型："required"（必选）或 "recommended"（建议）
2. 问题必须以“是否……？”开头
3. 提供原文关键证据（10-30字）
4. 严格按以下 JSON 格式输出，不要任何额外文本：

{
  "review_points": [
    {
      "type": "required",
      "question": "是否……？",
      "evidence": "原文关键句"
    }
  ]
}

【关注点】
{content}
""",
    "table": """
你是一名药品注册数据审核专家，请根据以下表格内容，生成表格完整性与合规性检查项。
要求：
1. 每条必须标注类型："required"（必选）或 "recommended"（建议）
2. 问题必须以“是否……？”开头
3. 提供原文关键证据（如表头列名）
4. 严格按以下 JSON 格式输出：

{
  "review_points": [
    {
      "type": "required",
      "question": "是否提供包含‘A、B、C’列的表格？",
      "evidence": "表头包含：A、B、C"
    }
  ]
}

【表格内容】
{content}
""",
    "example": """
你是一名药品注册文档审核专家，请根据以下【示例】内容，生成检查申报资料是否符合示例要求的审核点。
要求：
1. 每条必须标注类型："required"（必选）或 "recommended"（建议）
2. 问题必须以“是否……？”开头
3. 提供原文关键证据（如示例要素）
4. 严格按以下 JSON 格式输出：

{
  "review_points": [
    {
      "type": "required",
      "question": "是否参照示例提供……？",
      "evidence": "示例中包含：××、××"
    }
  ]
}

【示例】
{content}
""",
    "section": """
你是一名药品注册高级审评员，请根据以下章节（{section_id}）的全部技术要求、关注点、表格和示例，生成一份完整的审核清单。
要求：
1. 覆盖所有关键要素：处方、质量标准、方法验证、稳定性等
2. 每条必须标注类型："required"（必选）或 "recommended"（建议）
3. 问题必须以“是否……？”开头
4. 提供原文关键证据（10-30字）
5. 严格按以下 JSON 格式输出：

{
  "review_points": [
    {
      "type": "required",
      "question": "是否……？",
      "evidence": "原文关键句"
    }
  ]
}

章节内容：
{content}
"""
}

# ================== LLM 调用与解析 ==================
def call_llm(prompt: str, model: str = "qwen-max") -> list:
    try:
        response = Generation.call(
            model=model,
            prompt=prompt,
            temperature=0.5,
            max_tokens=800,
            timeout=60
        )
        if response.status_code != 200:
            print(f"❌ API 错误: {response.code} - {response.message}")
            return []
        return parse_llm_output(response.output.text)
    except Exception as e:
        print(f"⚠️ 调用失败: {e}")
        return []

def parse_llm_output(raw_output: str) -> list:
    """解析 LLM 的 JSON 输出"""
    try:
        # 提取 JSON 块
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', raw_output, re.DOTALL)
        if not json_match:
            json_match = re.search(r'(\{.*\})', raw_output, re.DOTALL)
        if not json_match:
            return []
        
        data = json.loads(json_match.group(1))
        points = []
        for item in data.get("review_points", []):
            if not all(k in item for k in ["type", "question", "evidence"]):
                continue
            if item["type"] not in ["required", "recommended"]:
                continue
            if not item["question"].startswith("是否"):
                continue
            points.append(item)
        return points
    except Exception as e:
        print(f"⚠️ JSON 解析失败: {e}")
        return []

# ================== Neo4j 操作 ==================
def save_review_point(driver, point: dict):
    query = """
    CREATE (:ReviewPoint {
      review_id: $review_id,
      section_id: $section_id,
      block_id: $block_id,
      block_type: $block_type,
      type: $type,
      question: $question,
      evidence: $evidence,
      source_text: $source_text,
      created_at: timestamp()
    })
    """
    with driver.session() as session:
        session.run(query, point)

def process_blocks(driver):
    query = """
    MATCH (l:Line)
    WHERE l.block_id IS NOT NULL
    WITH 
      l.block_id AS block_id,
      l.block_type AS block_type,
      l.parent_section AS section_id,
      collect(l.text) AS content,
      min(l.line_number) AS first_line
    ORDER BY first_line
    RETURN block_id, block_type, section_id, content
    """
    with driver.session() as session:
        result = session.run(query)
        for record in result:
            block_id = record["block_id"]
            block_type = record["block_type"]
            section_id = record["section_id"]
            content = "\n".join(record["content"])
            
            if block_type not in PROMPTS:
                continue
                
            prompt = PROMPTS[block_type].format(content=content)
            questions = call_llm(prompt, SELECTED_MODEL)
            
            for q in questions:
                save_review_point(driver, {
                    "review_id": f"RP_{block_id}_{hash(q['question']) % 10000}",
                    "section_id": section_id,
                    "block_id": block_id,
                    "block_type": block_type,
                    "type": q["type"],
                    "question": q["question"],
                    "evidence": q["evidence"],
                    "source_text": prompt
                })

def process_sections(driver):
    # 获取所有唯一 section_id（L3-L6）
    section_query = """
    MATCH (l:Line)
    WHERE l.section_path IS NOT NULL AND size(l.section_path) >= 3
    UNWIND l.section_path AS path
    WITH path WHERE path STARTS WITH '2.3.P.'
    RETURN DISTINCT path AS section_id
    ORDER BY section_id
    """
    with driver.session() as session:
        sections = [r["section_id"] for r in session.run(section_query)]
        
        for sec_id in sections:
            # 聚合该章节下所有非空 block 内容
            content_query = """
            MATCH (l:Line)
            WHERE ANY(p IN l.section_path WHERE p STARTS WITH $section_id)
              AND l.block_id IS NOT NULL
            RETURN collect(l.text) AS content
            """
            result = session.run(content_query, section_id=sec_id)
            content_list = result.single()["content"]
            if not content_list:
                continue
                
            content = "\n".join(content_list)
            prompt = PROMPTS["section"].format(section_id=sec_id, content=content)
            questions = call_llm(prompt, SELECTED_MODEL)
            print(questions)
            
            for q in questions:
                save_review_point(driver, {
                    "review_id": f"RP_SEC_{sec_id.replace('.', '_')}_{hash(q['question']) % 10000}",
                    "section_id": sec_id,
                    "block_id": None,  # ← 章节级无 block_id
                    "block_type": "section",  # ← 明确类型
                    "type": q["type"],
                    "question": q["question"],
                    "evidence": q["evidence"],
                    "source_text": prompt
                })

# ================== 主函数 ==================
def main():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    print("🔍 开始生成 block 级审核点...")
    process_blocks(driver)
    print("🔍 开始生成 section 级审核点...")
    process_sections(driver)
    driver.close()
    print("✅ 审核点生成完成！")

if __name__ == "__main__":
    main()