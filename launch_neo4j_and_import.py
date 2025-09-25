# launch_neo4j_and_import.py
import subprocess
import time
from config import CSV_DIR, NEO4J_CONTAINER_NAME, NEO4J_PASSWORD, NEO4J_VERSION

def main():
    print("🐳 正在启动 Neo4j 容器...")
    # 停止并删除旧容器
    subprocess.run(["docker", "stop", NEO4J_CONTAINER_NAME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["docker", "rm", NEO4J_CONTAINER_NAME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 启动新容器
    cmd = [
        "docker", "run", "-d",
        "--name", NEO4J_CONTAINER_NAME,
        "-p", "7474:7474", "-p", "7687:7687",
        "-v", f"{CSV_DIR.absolute()}:/var/lib/neo4j/import",
        "-e", f"NEO4J_AUTH=neo4j/{NEO4J_PASSWORD}",
        "-e", "NEO4J_PLUGINS='[\"apoc\"]'",
        f"neo4j:{NEO4J_VERSION}"
    ]
    print(f"🚀 运行命令: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    time.sleep(15)

    # 导入数据
    cypher = f"""
CREATE CONSTRAINT regulation_id IF NOT EXISTS FOR (r:Regulation) REQUIRE r.id IS UNIQUE;
CREATE CONSTRAINT section_id IF NOT EXISTS FOR (s:Section) REQUIRE s.id IS UNIQUE;
CREATE CONSTRAINT requirement_id IF NOT EXISTS FOR (req:Requirement) REQUIRE req.id IS UNIQUE;
CREATE CONSTRAINT checkpoint_id IF NOT EXISTS FOR (c:Checkpoint) REQUIRE c.id IS UNIQUE;

LOAD CSV WITH HEADERS FROM 'file:///regulations.csv' AS row
CREATE (:Regulation {{id: row.id, name: row.name, authority: row.authority, publish_date: date(row.publish_date)}});

LOAD CSV WITH HEADERS FROM 'file:///sections.csv' AS row
MATCH (r:Regulation {{id: row.regulation_id}})
CREATE (s:Section {{id: row.id, title: row.title}})
CREATE (r)-[:CONTAINS]->(s);

LOAD CSV WITH HEADERS FROM 'file:///requirements.csv' AS row
MATCH (s:Section {{id: row.section_id}})
CREATE (req:Requirement {{id: row.id, text: row.text}})
CREATE (s)-[:IMPLIES]->(req);

LOAD CSV WITH HEADERS FROM 'file:///checkpoints.csv' AS row
MATCH (req:Requirement {{id: row.requirement_id}})
CREATE (c:Checkpoint {{
  id: row.id,
  text: row.text,
  ctd_location: row.ctd_location,
  severity: row.severity
}})
CREATE (req)-[:MAPS_TO]->(c);
"""
    print("📥 正在导入数据到 Neo4j...")
    # 👇 新增：清空旧数据
    clear_neo4j_database()
    subprocess.run([
        "docker", "exec", "-i", NEO4J_CONTAINER_NAME,
        "cypher-shell", "-u", "neo4j", "-p", NEO4J_PASSWORD
    ], input=cypher.encode("utf-8"), check=True)

    print("\n✅ 知识图谱已构建完成！")
    print(f"   - Neo4j Browser: http://localhost:7474")
    print(f"   - 用户名: neo4j")
    print(f"   - 密码: {NEO4J_PASSWORD}")

# 在 launch_neo4j_and_import.py 的 import_data_to_neo4j() 函数开头添加：
def clear_neo4j_database():
    """清空 Neo4j 所有数据（保留约束）"""
    clear_cypher = """
    MATCH (n) DETACH DELETE n;
    """
    print("🗑️  正在清空 Neo4j 数据库...")
    subprocess.run([
        "docker", "exec", "-i", NEO4J_CONTAINER_NAME,
        "cypher-shell", "-u", "neo4j", "-p", NEO4J_PASSWORD
    ], input=clear_cypher.encode("utf-8"), check=True)

if __name__ == "__main__":
    main()