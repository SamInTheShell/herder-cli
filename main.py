from utils.input import input_box
from utils.llm import stream_llm_with_tools, fn_adapter_mcp2ollama, list_models, list_running_models, pull_model
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

# Debug flag to control debug output
ENABLE_DEBUG = False

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
    parser.add_argument('--system-prompt-message', type=str, default=None, help='System prompt as a string (takes precedence over --system-prompt)')
    parser.add_argument('--debug-mcp-servers', action='store_true', help='Enable MCP server debug output (do not suppress stderr)')
    parser.add_argument('--debug-herder', action='store_true', help='Enable herder debug output')
    args = parser.parse_args()

    global ENABLE_DEBUG
    ENABLE_DEBUG = args.debug_herder

    # Call set_debug_from_main to propagate ENABLE_DEBUG to llm.py
    import utils.llm
    utils.llm.set_debug_from_main(ENABLE_DEBUG)

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
    if args.system_prompt_message is not None:
        system_prompt = args.system_prompt_message
    elif os.path.exists(system_prompt_path):
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
    # Patch subprocess.Popen to redirect stderr to devnull for MCP servers only if debug is NOT enabled
    original_popen = subprocess.Popen
    if not args.debug_mcp_servers:
        def patched_popen(*args, **kwargs):
            # Redirect stderr to devnull for ALL subprocesses
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
        print()
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

        # /help should be first
        if user_input.lower().startswith("/help") or  user_input.startswith("/?"):
            print("\nAvailable commands:")
            print("  /help         Show this help message")
            print("  /model show   Show the current model")
            print("  /model set <model-name>   Set the model")
            print("  /history      Show chat history")
            print("  /tools        Show tool debug info")
            print("  /mcptools     Show raw MCP tools debug info")
            print("  /system set   Set the system prompt")
            print("  /system show  Show the current system prompt")
            print("  /ollama list  List available Ollama models")
            print("  /ollama ps    List running Ollama processes")
            print("  /ollama pull <model>   Pull a model from Ollama")
            print("  /exit         Exit the chat loop")
            print()
            continue

        # /model commands
        if user_input.lower().startswith("/model"):
            args = user_input.split(' ')
            if len(args) > 2 and args[1].lower() == "set":
                model = ' '.join(args[2:])
                print(f"  Model set to: {model}")
            elif len(args) > 1 and args[1].lower() == "show":
                print(f"Current model: {model}")
            else:
                print("  Options:")
                print("        /model set <model-name>")
                print("        /model show")
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
                if ENABLE_DEBUG:
                    tool_type = type(tool)
                    relevant_attrs = ['name', 'description', 'inputs', 'output_type']
                    other_attrs = [a for a in dir(tool) if not a.startswith('__') and a not in relevant_attrs]
                    print(f"\033[90m  DEBUG: Tool Info\033[0m")
                    print(f"\033[90m    Type: {tool_type} (module: {tool_type.__module__})\033[0m")
                    print(f"\033[90m    Bases: {[base.__name__ for base in tool_type.__bases__]}\033[0m")
                    doc = getattr(tool_type, '__doc__', None)
                    if doc:
                        print(f"\033[90m    Type docstring: {doc.strip()}\033[0m")
                    for attr in relevant_attrs:
                        print(f"\033[90m    {attr}: {getattr(tool, attr, 'N/A')}\033[0m")
                    print(f"\033[90m    Other attributes: {', '.join(other_attrs)}\033[0m")
                    print()
                print("name:        ", getattr(tool, "name", getattr(tool, "__name__", str(tool))))
                print("description: ", getattr(tool, "description", getattr(tool, "__doc__", "No description available.")))
            print("")
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

        # /ollama commands
        if user_input.lower().startswith("/ollama"):
            args = user_input.split()
            def safe_dict(obj):
                # Recursively convert objects to dicts and handle datetime
                if hasattr(obj, "__dict__"):
                    d = {}
                    for k, v in obj.__dict__.items():
                        if hasattr(v, "isoformat"):  # datetime
                            d[k] = v.isoformat()
                        elif hasattr(v, "__dict__"):  # nested object
                            d[k] = safe_dict(v)
                        elif isinstance(v, list):
                            d[k] = [safe_dict(i) for i in v]
                        elif callable(v):
                            continue
                        else:
                            d[k] = v
                    return d
                elif isinstance(obj, list):
                    return [safe_dict(i) for i in obj]
                else:
                    return obj
            if len(args) > 1 and args[1].lower() == "raw-list":
                print("\nOllama Raw Models Response:")
                models_response = list_models()
                print(json.dumps(safe_dict(models_response), indent=2, ensure_ascii=False))
                print()
                continue
            elif len(args) > 1 and args[1].lower() == "raw-ps":
                print("\nOllama Raw Processes Response:")
                processes_response = list_running_models()
                print(json.dumps(safe_dict(processes_response), indent=2, ensure_ascii=False))
                print()
                continue
            elif len(args) > 2 and args[1].lower() == "pull":
                model_name = ' '.join(args[2:])
                print(f"\nPulling Ollama model: {model_name}")
                try:
                    result_response = pull_model(model_name)
                    # Use model_dump if available, else safe_dict
                    if hasattr(result_response, "model_dump"):
                        result = result_response.model_dump()
                    else:
                        result = getattr(result_response, "dict", result_response)
                        def safe_dict(obj):
                            if hasattr(obj, "__dict__"):
                                d = {}
                                for k, v in obj.__dict__.items():
                                    if hasattr(v, "isoformat"):
                                        d[k] = v.isoformat()
                                    elif hasattr(v, "__dict__"):
                                        d[k] = safe_dict(v)
                                    elif isinstance(v, list):
                                        d[k] = [safe_dict(i) for i in v]
                                    elif callable(v):
                                        continue
                                    else:
                                        d[k] = v
                                return d
                            elif isinstance(obj, list):
                                return [safe_dict(i) for i in obj]
                            else:
                                return obj
                        result = safe_dict(result)
                    print(json.dumps(result, indent=2, ensure_ascii=False))
                except Exception as e:
                    print(json.dumps({"error": str(e)}, indent=2, ensure_ascii=False))
                print()
                continue
            else:
                print("  Options:")
                print("        /ollama raw-list")
                print("        /ollama raw-ps")
                print("        /ollama pull <model>")
                print()
                continue

        if user_input.lower().startswith("/call"):
            args = user_input.split(maxsplit=2)
            if len(args) < 2:
                print("Usage: /call toolname param1=value1 param2=value2 ... OR /call toolname {\"param1\":value1, ...}")
                print()
                continue
            toolname = args[1]
            params = {}
            # Support: /call toolname {json}
            if len(args) > 2 and args[2].strip().startswith('{') and args[2].strip().endswith('}'):
                try:
                    params = json.loads(args[2].strip())
                except Exception as e:
                    print(f"Error parsing JSON for tool params: {e}")
                    continue
            else:
                # Support: /call toolname param1=value1 param2=value2 ...
                for arg in args[2:] if len(args) > 2 else []:
                    for pair in arg.split():
                        if '=' in pair:
                            k, v = pair.split('=', 1)
                            v = v.strip()
                            if (v.startswith('{') and v.endswith('}')) or (v.startswith('[') and v.endswith(']')):
                                try:
                                    v = json.loads(v)
                                except Exception as e:
                                    print(f"Error parsing JSON for {k}: {e}")
                                    continue
                            params[k] = v
            tool = next((t for t in mcptools if getattr(t, "name", getattr(t, "__name__", str(t))) == toolname), None)
            if not tool:
                print(f"Tool '{toolname}' not found.")
                print()
                continue
            args_str = ', '.join(f"{k}={json.dumps(v) if isinstance(v, (dict, list)) else v}" for k, v in params.items())
            print(f"\n  \033[90mtool call:\033[0m {toolname}({args_str})")
            try:
                result = tool(**params)
                print(f"  \033[90mtool results:\033[90m \033[0m")
                print(f"{json.dumps(result, indent=2, ensure_ascii=False) if isinstance(result, (dict, list)) else result}")
                print(f"  \033[90m/end of tool results\033[90m \033[0m\n")
            except Exception as e:
                print(f"Error calling tool '{toolname}': {e}")
            print()
            continue

        if user_input.lower().startswith("/exit") or user_input.lower().startswith("/quit"):
            break

        if user_input.lower().startswith("/"):
            print("Run /help or /? for command options.")
            print()
            continue

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
