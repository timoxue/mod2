import dashscope
from dashscope import Generation

# 替换为你自己的 API Key
DASHSCOPE_API_KEY = "sk-57056cdaa1ec49c883e585d7ce1ea3d5"

def test_qwen(prompt: str, model_name: str = "qwen-max"):
    """
    调用通义千问模型进行文本生成
    
    Args:
        prompt (str): 用户输入的提示词
        model_name (str): 模型名称，可选: qwen-turbo, qwen-plus, qwen-max, qwen-max-longcontext 等
    
    Returns:
        str: 模型生成的回复
    """
    dashscope.api_key = DASHSCOPE_API_KEY
    
    try:
        response = Generation.call(
            model=model_name,
            prompt=prompt
        )
        if response.status_code == 200:
            return response.output.text
        else:
            return f"Error: {response.code} - {response.message}"
    except Exception as e:
        return f"Exception: {str(e)}"

if __name__ == "__main__":
    # 示例测试
    test_prompt = '''你是一名药品注册高级审评员，请根据以下章节（2.3.P.1）的全部技术要求、关注点、表格和示例，生成一份完整的审核清单。
要求：
1. 覆盖所有关键要素：处方、质量标准、方法验证、稳定性等；
2. 区分“必须项”和“建议项”；
3. 每条以“是否……？”开头，明确可检查内容；
4. 若涉及表格，检查其完整性；若涉及关注点，确保要求已落实；
5. 审核点应可直接用于注册文件自查或发补回复。

章节内容：
在处方组成列表中列出各成分的用量，包括辅料的内加/外加用量、pH值调
节剂用量（如适用）等。如投料涉及折干折纯，在处方下备注计算方法。惰性保
护气体无需列入处方，在处方下备注说明。对于包衣产品，在处方中列出素片和
包衣片的片重，在处方下备注说明包衣材料的成分信息。
成分
规格1
规格2
…… 过量
加入 作用 执行标准
用量 比例 用量 比例 ……
原料药
原料药1
原料药2
……
辅料
辅料1
辅料2
……
总量
工艺中使
用到并最
终去除的
溶剂

综合审核清单：'''
    print("提问:", test_prompt)
    answer = test_qwen(test_prompt)
    print("回答:", answer)