# -*- coding: utf-8 -*-
import json
import time
import docker
from neo4j import GraphDatabase
from pathlib import Path

# ================== 配置 ==================
JSON_FILE = "structured_lines.json"
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "password"
CONTAINER_NAME = "ctd-neo4j"

def main():
    json_path = Path(JSON_FILE)
    if not json_path.exists():
        raise FileNotFoundError(f"❌ {JSON_FILE} 不存在！")

    # 1. 启动 Neo4j 容器
    start_neo4j_container()

    # 2. 读取 JSON
    with open(json_path, "r", encoding="utf-8") as f:
        lines_data = json.load(f)

    # 3. 导入到 Neo4j
    import_to_neo4j(lines_data)

    print("✅ 导入完成！")
    print(f"   - Neo4j Browser: http://localhost:7474")
    print(f"   - 用户名: {NEO4J_USER}")
    print(f"   - 密码: {NEO4J_PASSWORD}")
    print("\n🔍 示例查询：")
    print("  按章节聚合：MATCH (l:Line) WHERE '2.3.P.2.1.1' IN l.section_path RETURN l.text LIMIT 5")
    print("  按块聚合：MATCH (l:Line {block_id: 'table_2_3_P_2_1_1_1'}) RETURN l.text")
    print("  查找章节下的所有【示例】【关注点】和表格：MATCH (l:Line) WHERE l.block_id IS NOT NULL AND ANY(path IN l.section_path WHERE path STARTS WITH '2.3.P.2.1.1') RETURN l.line_number, l.block_id, l.block_type, l.text ORDER BY l.line_number")

def start_neo4j_container():
    """启动 Neo4j 5.14 容器"""
    client = docker.from_env()
    
    # 停止并删除旧容器
    try:
        old_container = client.containers.get(CONTAINER_NAME)
        old_container.stop()
        old_container.remove()
    except docker.errors.NotFound:
        pass

    # 启动新容器
    print("🐳 启动 Neo4j 5.14 容器...")
    client.containers.run(
        "neo4j:5.14",
        name=CONTAINER_NAME,
        ports={"7474/tcp": 7474, "7687/tcp": 7687},
        environment={
            "NEO4J_AUTH": f"{NEO4J_USER}/{NEO4J_PASSWORD}",
            "NEO4J_PLUGINS": '["apoc"]'
        },
        detach=True,
        remove=False
    )
    time.sleep(20)  # 等待启动

def import_to_neo4j(lines_data):
    """将 structured_lines.json 导入 Neo4j"""
    print(f"📥 正在导入 {len(lines_data)} 行数据到 Neo4j...")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    with driver.session() as session:
        # 创建约束
        session.run("CREATE CONSTRAINT line_number_unique IF NOT EXISTS FOR (l:Line) REQUIRE l.line_number IS UNIQUE")
        # 创建索引
        session.run("CREATE INDEX section_path_idx IF NOT EXISTS FOR (l:Line) ON (l.section_path)")
        session.run("CREATE INDEX block_id_idx IF NOT EXISTS FOR (l:Line) ON (l.block_id)")

        # 批量导入
        query = """
        UNWIND $lines AS line
        CREATE (:Line {
            line_number: line.line_number,
            text: line.text,
            section_path: line.section_path,
            parent_section: line.parent_section,
            block_type: line.block_type,
            block_id: line.block_id
        })
        """
        session.run(query, lines=lines_data)

    driver.close()
    print("✅ 数据导入成功！")

if __name__ == "__main__":
    main()