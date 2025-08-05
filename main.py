from utils.input import input_box
from utils.llm import stream_llm_with_tools, fn_adapter_mcp2ollama
import datetime
import json
from pyfiglet import figlet_format
import os
import sys
import argparse

import mcp
from mcp import StdioServerParameters
from mcpadapt.core import MCPAdapt
from mcpadapt.smolagents_adapter import SmolAgentsAdapter

COMMAND_NAME="herder-cli"
COMMAND_VERSION="v0.1"

DEFAULT_SYSTEM_PROMPT = "No system prompt was given. Follow all user instructions and requests."

def main():
    parser = argparse.ArgumentParser(description=COMMAND_NAME)
    parser.add_argument('--prompt', type=str, default=None, help='Single-shot prompt (skip chat loop)')
    parser.add_argument('--history-file', type=str, default=None, help='Path to message history file')
    parser.add_argument('--no-banner', action='store_true', help='Suppress banner output')
    parser.add_argument('--mcp-config', type=str, default=None, help='Path to MCP config file (JSON)')
    parser.add_argument('--model', type=str, default="mistral-small3.2:24b", help='Model name for Ollama')
    parser.add_argument('--system-prompt', type=str, default="herder-instructions.md", help='Path to system prompt file (default: herder-instructions.md)')
    args = parser.parse_args()

    devnull = open(os.devnull, 'w')
    model = args.model
    messages = []
    if args.history_file:
        try:
            with open(args.history_file, 'r') as f:
                messages = json.load(f)
        except Exception:
            messages = []

    tools=[]
    # System prompt file logic
    system_prompt_path = args.system_prompt
    if os.path.exists(system_prompt_path):
        with open(system_prompt_path, 'r') as f:
            system_prompt = f.read()
    else:
        if system_prompt_path == "herder-instructions.md":
            system_prompt = DEFAULT_SYSTEM_PROMPT
        else:
            print(f"Error: System prompt file '{system_prompt_path}' not found.")
            sys.exit(1)

    if not args.no_banner:
        banner = figlet_format(COMMAND_NAME, font="slant")
        banner = banner[:-(len(COMMAND_VERSION))] + COMMAND_VERSION
        print(gradient_rainbowify(banner))
        print()
        print()

    # Connect to MCP server and get tools - suppress server logs
    # Use subprocess-level redirection to suppress MCP server output
    import subprocess
    # Patch subprocess.Popen to redirect stderr to devnull for MCP servers
    original_popen = subprocess.Popen
    def patched_popen(*args, **kwargs):
        # Only redirect stderr for our MCP server commands
        if args and len(args[0]) > 0:
            cmd = args[0] if isinstance(args[0], list) else [args[0]]
            if any("assistant-mcp-server" in str(c) or "pubmedmcp" in str(c) for c in cmd):
                kwargs['stderr'] = devnull
        return original_popen(*args, **kwargs)
    subprocess.Popen = patched_popen


    # Only load MCP servers from config if provided
    mcp_servers = []
    if args.mcp_config:
        try:
            with open(args.mcp_config, 'r') as f:
                mcp_config = json.load(f)
            for server in mcp_config.get('servers', []):
                mcp_servers.append(StdioServerParameters(
                    command=server['command'],
                    args=server.get('args', [])
                ))
        except Exception as e:
            print(f"Error loading MCP config: {e}")
            # mcp_servers remains empty
    try:
        if mcp_servers:
            with MCPAdapt(mcp_servers, SmolAgentsAdapter()) as mcptools:
                run_main_logic(args, model, messages, system_prompt, mcptools)
        else:
            mcptools = []
            run_main_logic(args, model, messages, system_prompt, mcptools)
    finally:
        subprocess.Popen = original_popen
        devnull.close()

def run_main_logic(args, model, messages, system_prompt, mcptools):
    if args.prompt is not None:
        user_input = f"""
        Additional Info From User Client:
        Current timestamp: {get_timestamp()}
        --- Begin User Message ---
        {args.prompt}
        """
        print(f"\033[90m  User ({get_timestamp()}):\033[0m")
        print(args.prompt)
        print()
        print(f"\033[90m  Assistant ({get_timestamp()}):\033[0m")
        tools_ollama = fn_adapter_mcp2ollama(mcptools)
        messages = stream_llm_with_tools(model=model, user_input=user_input, tools=tools_ollama, system_prompt=system_prompt, messages=messages, mcptools=mcptools)
        if args.history_file:
            with open(args.history_file, 'w') as f:
                json.dump(messages, f, indent=2, ensure_ascii=False)
        return

    messages = chat(model=model, messages=messages, system_prompt=system_prompt, mcptools=mcptools)
    if args.history_file:
        with open(args.history_file, 'w') as f:
            json.dump(messages, f, indent=2, ensure_ascii=False)

def chat(
    model: str = "mistral-small3.2:24b",
    messages: list = None,
    mcptools: list = None,
    system_prompt: str = "You are a helpful AI assistant named Bob, an expert in cryptography."
) -> list:
    """
    AI Chat Event Loop
    Args:
        model (str): Model name for Ollama.
        messages (list): List of chat messages.
        tools (list): List of tool callables.
        system_prompt (str): System prompt for the LLM.
    Returns:
        list: Updated messages list.
    """
    if messages is None:
        messages = []

    while True:
        user_input = input_box()

        if user_input is None:
            break

        if user_input.lower().startswith("/help"):
            print("\nAvailable commands:")
            print("  /help         Show this help message")
            print("  /history      Show chat history")
            print("  /tools        Show tool debug info")
            print("  /mcptools     Show raw MCP tools debug info")
            print("  /system set   Set the system prompt")
            print("  /system show  Show the current system prompt")
            print("  /exit         Exit the chat loop")
            print()
            continue

        if user_input.lower().startswith("/history"):
            print(json.dumps(messages, indent=2, ensure_ascii=False))
            continue

        if user_input.lower().startswith("/tools"):
            print()
            print("Tool Debug Info:")
            for tool in mcptools:
                print()
                print("name:        ", getattr(tool, "name", getattr(tool, "__name__", str(tool))))
                print("description: ", getattr(tool, "description", getattr(tool, "__doc__", "No description available.")))
            continue

        if user_input.lower().startswith("/mcptools"):
            print()
            print("Raw MCP Tools Debug Info:")
            for tool in mcptools:
                print()
                print("name:        ", getattr(tool, "name", getattr(tool, "__name__", str(tool))))
                print("description: ", getattr(tool, "description", getattr(tool, "__doc__", "No description available.")))
                print("inputs:      ", getattr(tool, "inputs", "N/A"))
                print("output_type: ", getattr(tool, "output_type", "N/A"))
            continue

        if user_input.lower().startswith("/system"):
            args = user_input.split(' ')
            if len(args) > 2 and args[1].lower() == "set":
                system_prompt = ' '.join(args[2:])
                print(f"  System prompt set to:")
                print(f"{system_prompt}")

            elif len(args) > 1 and args[1].lower() == "show":
                try:
                    print(f"Current system prompt:")
                    print(f"{system_prompt}")
                except NameError:
                    print("System prompt is not set.")
            else:
                print("  Options:")
                print("        /system set")
                print("        /system show")

            print()
            continue

        if user_input.lower().startswith("/exit") or user_input.lower().startswith("/exit"):
            break

        if user_input.strip() == "":
            continue

        print(f"\033[90m  User ({get_timestamp()}):\033[0m")

        print(f"{user_input}")
        print()


        # Inject some contextual info into the chat.
        user_input = f"""
                Additional Info From User Client:
                Current timestamp: {get_timestamp()}
                --- Begin User Message ---
                {user_input}
                """

        print(f"\033[90m  Assistant ({get_timestamp()}):\033[0m")
        tools = fn_adapter_mcp2ollama(mcptools)
        messages = stream_llm_with_tools(model=model, user_input=user_input, tools=tools, system_prompt=system_prompt, messages=messages, mcptools=mcptools)
        print()
        print()

    return messages

# Gradient rainbowify: color each line with a different color
colors = [31, 33, 32, 36, 34, 35]  # ANSI color codes: red, yellow, green, cyan, blue, magenta
def gradient_rainbowify(text):
    lines = text.splitlines()
    result = ""
    for i, line in enumerate(lines):
        color = colors[i % len(colors)]
        result += f"\033[1;{color}m{line}\033[0m\n"
    return result

def get_timestamp() -> str:
    """
    Returns the current timestamp in ISO 8601 format.
    """
    return datetime.datetime.now().isoformat()

if __name__ == "__main__":
    main()
