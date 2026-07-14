"""LLM 初始化模块 — 支持多模型切换

支持的 LLM 提供商:
    - deepseek:          ChatDeepSeek (langchain_deepseek)
    - openai_compatible: ChatOpenAI   (langchain_openai)，兼容任何 OpenAI API 格式的服务

配置方式:
    在 .env 文件中设置:
        LLM_PROVIDER=deepseek          # 模型提供商
        LLM_MODEL=deepseek-chat        # 模型名称
        LLM_TEMPERATURE=0.1            # 温度参数
        DEEPSEEK_API_KEY=sk-xxx        # DeepSeek API Key
        OPENAI_API_KEY=sk-xxx          # OpenAI API Key
        OPENAI_BASE_URL=https://...    # OpenAI 兼容 API 地址（可选）
"""

import os
from dotenv import load_dotenv

load_dotenv()

# 从环境变量读取配置
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "deepseek")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.1"))


def create_llm():
    """
    根据配置创建 LLM 实例。

    Returns:
        对应提供商的 ChatModel 实例

    Raises:
        ValueError: 缺少 API Key 或不支持的提供商
    """
    # ===== DeepSeek =====
    if LLM_PROVIDER == "deepseek":
        from langchain_deepseek import ChatDeepSeek
        from pydantic import SecretStr

        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("请在 .env 中设置 DEEPSEEK_API_KEY")

        print(f"  🤖 LLM 初始化: DeepSeek / {LLM_MODEL} (temperature={LLM_TEMPERATURE})")
        return ChatDeepSeek(
            model=LLM_MODEL,
            temperature=LLM_TEMPERATURE,
            api_key=SecretStr(api_key),
        )

    # ===== OpenAI 兼容接口 =====
    elif LLM_PROVIDER == "openai_compatible":
        from langchain_openai import ChatOpenAI

        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        if not api_key:
            raise ValueError("请在 .env 中设置 OPENAI_API_KEY")

        print(f"  🤖 LLM 初始化: OpenAI Compatible / {LLM_MODEL} (temperature={LLM_TEMPERATURE})")
        return ChatOpenAI(
            model=LLM_MODEL,
            temperature=LLM_TEMPERATURE,
            api_key=api_key,
            base_url=base_url,
        )

    else:
        raise ValueError(f"不支持的 LLM_PROVIDER: {LLM_PROVIDER}，可选: deepseek / openai_compatible")
