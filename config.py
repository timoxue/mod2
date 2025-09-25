# config.py
from pathlib import Path

# === 输入 PDF 文件路径 ===
PDF_FILE = Path("化学药品仿制药上市许可申请模块二药学资料撰写要求（制剂）（试行）.pdf")

# === 工作目录 ===
WORK_DIR = Path("ctd_kg_pipeline_output")
CSV_DIR = WORK_DIR / "csv"

# === Neo4j 配置 ===
NEO4J_CONTAINER_NAME = "ctd-neo4j"
NEO4J_PASSWORD = "password"
NEO4J_VERSION = "5.14"  # Neo4j Docker 镜像版本

# === 确保路径存在 ===
WORK_DIR.mkdir(exist_ok=True)
CSV_DIR.mkdir(exist_ok=True)