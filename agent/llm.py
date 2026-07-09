"""LLM 初始化模块 - 支持多模型切换"""
import os
from dotenv import load_dotenv

load_dotenv()

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "deepseek")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.1"))


def create_llm():
    """根据配置创建对应的 LLM 实例"""
    if LLM_PROVIDER == "deepseek":
        from langchain_deepseek import ChatDeepSeek
        from pydantic import SecretStr

        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("请在 .env 中设置 DEEPSEEK_API_KEY")

        return ChatDeepSeek(
            model=LLM_MODEL,
            temperature=LLM_TEMPERATURE,
            api_key=SecretStr(api_key),
        )

    elif LLM_PROVIDER == "openai_compatible":
        from langchain_openai import ChatOpenAI

        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        if not api_key:
            raise ValueError("请在 .env 中设置 OPENAI_API_KEY")

        return ChatOpenAI(
            model=LLM_MODEL,
            temperature=LLM_TEMPERATURE,
            api_key=api_key,
            base_url=base_url,
        )

    else:
        raise ValueError(f"不支持的 LLM_PROVIDER: {LLM_PROVIDER}，可选: deepseek / openai_compatible")
