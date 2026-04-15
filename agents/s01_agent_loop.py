#!/usr/bin/env python3
# Harness: the loop -- the model's first connection to the real world.
"""
s01_agent_loop.py - The Agent Loop

The entire secret of an AI coding agent in one pattern:

    while stop_reason == "tool_use":
        response = LLM(messages, tools)
        execute tools
        append results

    +----------+      +-------+      +---------+
    |   User   | ---> |  LLM  | ---> |  Tool   |
    |  prompt  |      |       |      | execute |
    +----------+      +---+---+      +----+----+
                          ^               |
                          |   tool_result |
                          +---------------+
                          (loop continues)

This is the core loop: feed tool results back to the model
until the model decides to stop. Production agents layer
policy, hooks, and lifecycle controls on top.
"""

import os
import subprocess

# 导入readline模块并配置，用于优化命令行交互体验
try:
    import readline
    # #143 UTF-8 backspace fix for macOS libedit
    # 修复macOS上libedit库处理UTF-8字符和退格键的问题
    readline.parse_and_bind('set bind-tty-special-chars off')  # 关闭终端特殊字符绑定
    readline.parse_and_bind('set input-meta on')  # 允许输入元字符
    readline.parse_and_bind('set output-meta on')  # 允许输出元字符
    readline.parse_and_bind('set convert-meta off')  # 不转换元字符
    readline.parse_and_bind('set enable-meta-keybindings on')  # 启用元键绑定
except ImportError:
    # 如果环境中没有readline模块（如某些Windows环境），则静默忽略
    pass

# 导入Anthropic SDK，用于与Claude等AI模型进行交互
from anthropic import Anthropic
# 导入dotenv库，用于从.env文件加载环境变量
from dotenv import load_dotenv

# 加载环境变量，override=True表示覆盖已有的环境变量
load_dotenv(override=True)

# 如果设置了自定义的Anthropic API基础URL，则移除可能存在的认证令牌
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

# 创建Anthropic客户端实例
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
# 从环境变量中获取模型ID
MODEL = os.environ["MODEL_ID"]

# 系统提示，定义AI的角色和行为
SYSTEM = f"You are a coding agent at {os.getcwd()}. Use bash to solve tasks. Act, don't explain."

# 定义AI代理可以使用的工具列表
# 这里只定义了一个bash工具，用于执行shell命令
TOOLS = [{
    "name": "bash",  # 工具名称
    "description": "Run a shell command.",  # 工具描述
    "input_schema": {  # 工具输入参数的模式定义（JSON Schema格式）
        "type": "object",
        "properties": {"command": {"type": "string"}},  # 要求提供command参数
        "required": ["command"],  # command参数是必需的
    },
}]


# run_bash函数：执行shell命令并返回执行结果
# 类型提示：接受string类型参数，返回string类型结果
def run_bash(command: str) -> str:
    # 定义危险命令列表，用于安全检查
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    
    # 使用any()函数和生成器表达式检查命令是否包含危险操作
    # 遍历dangerous列表中的每个元素d，检查d是否在command中
    # 如果任何一个危险片段存在，返回错误信息
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    
    try:
        # 执行shell命令
        # shell=True：使用shell解释器执行命令
        # cwd=os.getcwd()：在当前工作目录执行命令
        # capture_output=True：捕获命令的标准输出和标准错误
        # text=True：将输出以文本形式（字符串）返回
        # timeout=120：命令执行的超时时间为120秒
        r = subprocess.run(command, shell=True, cwd=os.getcwd(),
                           capture_output=True, text=True, timeout=120)
        
        # 合并标准输出和标准错误，并去除两端空白
        out = (r.stdout + r.stderr).strip()
        
        # 条件表达式：如果out不为空，返回前50000个字符；否则返回"(no output)"
        # 限制输出长度，防止命令产生过多输出导致API调用失败或内存占用过高
        return out[:50000] if out else "(no output)"
    
    except subprocess.TimeoutExpired:
        # 处理命令执行超时的情况
        return "Error: Timeout (120s)"
    except (FileNotFoundError, OSError) as e:
        # 处理文件未找到或操作系统错误的情况
        return f"Error: {e}"


# -- The core pattern: a while loop that calls tools until the model stops --
def agent_loop(messages: list):
    while True:
        # 调用Anthropic API生成响应
        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=TOOLS, max_tokens=8000,
        )
        
        # 将模型的回复以assistant角色添加到对话历史中
        # Anthropic API要求消息必须包含role字段，用于标识消息的发送者角色
        messages.append({"role": "assistant", "content": response.content})
        
        # 如果模型没有调用工具，说明任务已完成，退出循环
        if response.stop_reason != "tool_use":
            return
        
        # 执行每个工具调用，收集结果
        results = []
        for block in response.content:
            if block.type == "tool_use":
                # 打印要执行的命令（黄色文本）
                print(f"\033[33m$ {block.input['command']}\033[0m")
                # 执行命令并获取输出
                output = run_bash(block.input["command"])
                # 打印命令输出的前200个字符
                print(output[:200])
                # 将工具执行结果添加到results列表
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": output})
        
        # 将工具执行结果以user角色添加到对话历史中
        # Anthropic API要求工具执行结果必须以user角色提交，这样模型才能正确理解这是对之前工具调用的响应
        messages.append({"role": "user", "content": results})


if __name__ == "__main__":
    # 存储对话历史的列表
    history = []
    
    while True:
        try:
            # 显示命令行输入提示，青色文本显示"s01 >> "
            # \033[36m：ANSI转义序列，设置文本颜色为青色
            # \033[0m：ANSI转义序列，重置文本颜色为默认颜色
            query = input("\033[36ms01 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            # 处理EOF错误（Ctrl+D）或键盘中断（Ctrl+C）
            break
        
        # 检查用户是否输入了退出命令
        # query.strip()：去除两端空白字符
        # .lower()：转换为小写，实现大小写不敏感的匹配
        # in ("q", "exit", "")：检查是否在退出命令列表中
        if query.strip().lower() in ("q", "exit", ""):
            break
        
        # 将用户输入以user角色添加到对话历史中
        history.append({"role": "user", "content": query})
        
        # 调用agent_loop函数处理对话
        agent_loop(history)
        
        # 获取对话历史的最后一个元素的content部分
        # history[-1]：使用负索引访问列表的最后一个元素
        response_content = history[-1]["content"]
        
        # 处理并显示模型的响应
        # 如果响应内容是列表（符合Anthropic API的标准格式）
        if isinstance(response_content, list):
            # 遍历列表中的每个内容块
            for block in response_content:
                # 检查每个块是否有text属性（即文本内容）
                if hasattr(block, "text"):
                    # 打印文本内容
                    print(block.text)
        
        # 打印空行，提高输出可读性
        print()
