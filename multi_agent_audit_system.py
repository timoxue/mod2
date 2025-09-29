# -*- coding: utf-8 -*-
import json
import re
from typing import List, Dict
from dashscope import Generation
import os

os.environ['DASHSCOPE_API_KEY'] = 'sk-57056cdaa1ec49c883e585d7ce1ea3d5'

# Neo4j 工具（保持不变）
from neo4j import GraphDatabase
driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password"))

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

# ================== 多模型调用（使用 DashScope 原生 API） ==================
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
if not DASHSCOPE_API_KEY:
    raise ValueError("请设置 DASHSCOPE_API_KEY")

# 仅使用 DashScope 支持的 Qwen 模型
MODELS = {
    "qwen_max": "qwen-max",
    "qwen_plus": "qwen-plus",
    "qwen_turbo": "qwen-turbo"
}

def call_dashscope(model: str, prompt: str) -> str:
    """调用 DashScope 原生 API"""
    try:
        response = Generation.call(
            model=model,
            prompt=prompt,
            api_key=DASHSCOPE_API_KEY,
            temperature=0.5,
            max_tokens=800,
            timeout=60
        )
        if response.status_code == 200:
            return response.output.text
        else:
            print(f"❌ API 错误 ({model}): {response.code} - {response.message}")
            return ""
    except Exception as e:
        print(f"⚠️ 调用失败 ({model}): {e}")
        return ""

# ================== ReAct Prompt（简化版，不依赖 LangChain） ==================
def build_react_prompt(input_text: str, tools_desc: str) -> str:
    return f"""
你是一个药品注册审核智能体，请严格按 ReAct 格式输出。
可用工具：
{tools_desc}

使用格式：
Thought: ...
Action: get_block_content 或 get_section_content
Action Input: "具体ID"
Observation: <工具返回内容>

Thought: 现在生成审核点
Action: Final Answer
Action Input: {{"review_points": [{{"type": "...", "question": "...", "evidence": "...", "source_block_id": "...", "source_section_id": "..."}}]}}

Question: {input_text}
"""

# ================== 主流程 ==================
def generate_audit_points(target_id: str, id_type: str = "block"):
    # 1. 构建工具描述
    tools_desc = (
        "get_block_content(block_id: str): 获取 block 原文\n"
        "get_section_content(section_id: str): 获取 section 原文"
    )
    
    # 2. 初始 Prompt
    input_text = f"为 {id_type}_id='{target_id}' 生成审核点"
    prompt = build_react_prompt(input_text, tools_desc)
    
    all_outputs = []
    for name, model in MODELS.items():
        print(f"🔍 {name} 正在生成...")
        
        # 模拟 ReAct 工具调用（简化：直接注入内容）
        if id_type == "block":
            content = get_block_content(target_id)
            tool_output = f"Observation: {content}"
        else:
            content = get_section_content(target_id)
            tool_output = f"Observation: {content}"
        
        # 替换 Prompt 中的工具调用
        full_prompt = prompt + "\nThought: 获取内容\nAction: get_block_content\nAction Input: \"" + target_id + "\"\n" + tool_output
        
        # 调用模型
        raw_output = call_dashscope(model, full_prompt)
        if raw_output:
            # 解析 JSON
            json_match = re.search(r'Action Input:\s*({.*})', raw_output, re.DOTALL)
            if json_match:
                try:
                    data = json.loads(json_match.group(1))
                    for point in data.get("review_points", []):
                        point["source_model"] = name
                    all_outputs.append(data.get("review_points", []))
                except:
                    pass
    
    # 3. 仲裁（同前）
    from collections import defaultdict
    unique_points = {}
    for points in all_outputs:
        for p in points:
            key = p["question"]
            if key not in unique_points:
                unique_points[key] = p
                unique_points[key]["source_models"] = [p["source_model"]]
            else:
                unique_points[key]["source_models"].append(p["source_model"])
    
    final_points = []
    for p in unique_points.values():
        p["type"] = "required" if len(p["source_models"]) >= 2 else "recommended"
        p["source_models"] = list(set(p["source_models"]))
        final_points.append(p)
    
    # 4. 保存到 Neo4j（同前）
    query = """
    CREATE (:ReviewPoint {
      review_id: $review_id,
      block_id: $block_id,
      section_id: $section_id,
      type: $type,
      question: $question,
      evidence: $evidence,
      source_models: $source_models,
      created_at: timestamp()
    })
    """
    with driver.session() as session:
        for p in final_points:
            session.run(query, {
                "review_id": f"RP_{p.get('source_block_id', p['source_section_id']).replace('.', '_')}_{hash(p['question']) % 10000}",
                "block_id": p.get("source_block_id"),
                "section_id": p["source_section_id"],
                "type": p["type"],
                "question": p["question"],
                "evidence": p["evidence"],
                "source_models": p["source_models"]
            })
    
    print(f"✅ 生成 {len(final_points)} 条审核点")
    return final_points

if __name__ == "__main__":
    points = generate_audit_points("concern_2_3_P_2_1_1_1", "block")
    for p in points[:2]:
        print(f"[{p['type']}] {p['question']}")