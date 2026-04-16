#!/usr/bin/env python3
# Harness: tool dispatch -- expanding what the model can reach.
"""
s02_tool_use.py - Tools

The agent loop from s01 didn't change. We just added tools to the array
and a dispatch map to route calls.

    +----------+      +-------+      +------------------+
    |   User   | ---> |  LLM  | ---> | Tool Dispatch    |
    |  prompt  |      |       |      | {                |
    +----------+      +---+---+      |   bash: run_bash |
                          ^          |   read: run_read |
                          |          |   write: run_wr  |
                          +----------+   edit: run_edit |
                          tool_result| }                |
                                     +------------------+

Key insight: "The loop didn't change at all. I just added tools."
"""

import os
import subprocess
from pathlib import Path

from _runtime import MODEL, create_message_with_retry

WORKDIR = Path.cwd()

SYSTEM = f"You are a coding agent at {WORKDIR}. Use tools to solve tasks. Act, don't explain."

# 越界保护
def safe_path(p: str) -> Path:
    """
    safe_path 函数：确保路径在工作目录内，防止路径越界
    
    参数：
    - p: str - 输入的路径字符串
    
    返回值：
    - Path - pathlib.Path 类型的路径对象
    
    类型提示说明：
    - -> Path 是 Python 的类型提示语法，表示函数返回值类型是 Path 类型
    - Path 是从 pathlib 模块导入的类，用于表示文件系统路径
    - 函数内部的 path 变量（小写）是存储路径对象的变量名
    - 大写的 Path 是类型名称，小写的 path 是变量名称
    """
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"


# run_read 函数：读取文件内容
# 参数说明：
# - path: str - 文件路径
# - limit: int = None - 行数限制，默认值为 None（读取全部内容）
def run_read(path: str, limit: int = None) -> str:
    try:
        # 调用 safe_path 函数获取安全的路径对象，然后读取文件内容
        # safe_path 函数会确保路径在工作目录内，防止路径越界
        text = safe_path(path).read_text()
        
        # splitlines() 方法：将文本按换行符分割成列表
        # 会处理不同平台的换行符（\n、\r\n 等），确保跨平台兼容性
        lines = text.splitlines()
        
        # 如果设置了 limit 且文件行数超过 limit，则只保留前 limit 行
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        
        # "\n".join(lines)：将行列表重新连接成字符串
        # [:50000]：限制返回内容长度为50000字符，防止内容过大
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"


# run_write 函数：写入文件内容
# 参数说明：
# - path: str - 文件路径
# - content: str - 要写入的内容
def run_write(path: str, content: str) -> str:
    try:
        # 获取安全的路径对象
        fp = safe_path(path)
        
        # 确保文件所在的目录结构存在
        # parents=True：递归创建父目录
        # exist_ok=True：如果目录已存在，不会抛出异常
        fp.parent.mkdir(parents=True, exist_ok=True)
        
        # write_text() 方法：将内容写入文件
        # 默认行为：如果文件不存在则创建，存在则覆盖
        # 默认使用 UTF-8 编码
        fp.write_text(content)
        
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"


# run_edit 函数：编辑文件内容，替换指定文本
def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = safe_path(path)
        content = fp.read_text()
        if old_text not in content:
            return f"Error: Text not found in {path}"
        fp.write_text(content.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


# -- The dispatch map: {tool_name: handler} --
# TOOL_HANDLERS 是工具处理器映射，用于根据工具名称调度到对应的处理函数
# 键是工具名称，值是 lambda 函数，用于调用相应的处理函数
# 使用 **kw 参数接收任意关键字参数，根据工具需要提取相应的值
TOOL_HANDLERS = {
    # "bash" 工具：执行 shell 命令
    "bash":       lambda **kw: run_bash(kw["command"]),
    # "read_file" 工具：读取文件内容，limit 是可选参数
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    # "write_file" 工具：写入文件内容
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    # "edit_file" 工具：编辑文件内容，替换指定文本
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
}

TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
]


def agent_loop(messages: list):
    while True:
        response = create_message_with_retry(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=TOOLS, max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return
        results = []
        for block in response.content:
            if block.type == "tool_use":
                handler = TOOL_HANDLERS.get(block.name)
                output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                print(f"> {block.name}:")
                print(output[:200])
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
        messages.append({"role": "user", "content": results})


if __name__ == "__main__":
    history = []
    while True:
        try:
            query = input("\033[36ms02 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        agent_loop(history)
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if hasattr(block, "text"):
                    print(block.text)
        print()
