# my_agent_v1.py - 适配 LangChain 1.3.11
import os
from dotenv import load_dotenv
from pydantic import SecretStr

# ⭐ 关键：使用 langchain_classic 的导入路径
from langchain_classic.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import tool
from langchain_deepseek import ChatDeepSeek

# ==========================================
# 1. 加载环境变量和初始化模型
# ==========================================
load_dotenv()

deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
if deepseek_api_key is None:
    raise ValueError("请在 .env 中设置 DEEPSEEK_API_KEY")

llm = ChatDeepSeek(
    model="deepseek-chat",
    temperature=0.1,
    api_key=SecretStr(deepseek_api_key)
)

# ==========================================
# 2. 定义工具
# ==========================================

@tool
def list_files(directory_path: str) -> str:
    """列出指定目录下的所有文件和文件夹。使用绝对路径。"""
    try:
        if not os.path.exists(directory_path):
            return f"错误：路径 '{directory_path}' 不存在。"
        items = os.listdir(directory_path)
        return f"目录 '{directory_path}' 中的内容:\n" + "\n".join(items)
    except Exception as e:
        return f"操作失败: {str(e)}"

@tool
def execute_adb_command(command: str) -> str:
    """
    执行一条ADB命令，并返回其输出。
    命令中不要包含'adb'前缀，例如：
    - 'devices'
    - 'shell screencap -p /sdcard/screen.png'
    """
    import subprocess
    try:
        full_command = ["adb"] + command.split()
        result = subprocess.run(full_command, capture_output=True, text=True, timeout=30)
        output = result.stdout
        if result.stderr:
            output += f"\n标准错误: {result.stderr}"
        return output.strip()
    except subprocess.TimeoutExpired:
        return "错误：ADB命令执行超时。"
    except Exception as e:
        return f"执行ADB命令时出错: {str(e)}"

# ==========================================
# 3. 创建并运行智能体
# ==========================================

system_prompt = """你是一个运行在Mac电脑上的智能助手，可以帮用户浏览文件系统，并通过ADB控制已连接的Android手机。
你能够准确理解并执行文件操作和ADB命令。
请用中文回答。"""

prompt = ChatPromptTemplate.from_messages([
    ("system", system_prompt),
    MessagesPlaceholder(variable_name="chat_history", optional=True),
    ("human", "{input}"),
    MessagesPlaceholder(variable_name="agent_scratchpad"),
])

tools = [list_files, execute_adb_command]
agent = create_tool_calling_agent(llm, tools, prompt)
agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

def chat_with_agent():
    print("\n✅ 智能体已启动！我可以帮你浏览Mac文件、操作Android手机。输入 'quit' 退出。\n")
    chat_history = []
    
    while True:
        try:
            user_input = input("你: ")
            if user_input.lower() in ['quit', 'exit', 'q']:
                print("👋 再见！")
                break
            
            response = agent_executor.invoke({
                "input": user_input,
                "chat_history": chat_history
            })
            agent_response = response['output']
            print(f"\n🤖 智能体: {agent_response}\n")
            
            chat_history.extend([
                ("human", user_input),
                ("ai", agent_response)
            ])
            
        except KeyboardInterrupt:
            print("\n👋 再见！")
            break
        except Exception as e:
            print(f"\n❌ 发生错误: {str(e)}\n")

if __name__ == "__main__":
    chat_with_agent()