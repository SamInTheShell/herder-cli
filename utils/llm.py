import ollama
from typing import List, Callable, Optional, Iterator
import json

# Debug flag to control debug output
ENABLE_DEBUG = False

def stream_llm_with_tools(model: str, user_input: str, tools: Optional[List[Callable]] = None, system_prompt: Optional[str] = None, enable_thinking: bool = False, messages : List = [], mcptools: Optional[List] = None):
    """
    Streams responses from an LLM and allows sequential tool calls.

    Args:
        model (str): The model name for Ollama.
        user_input (str): The initial user input.
        tools (List[Callable]): List of callable tool functions.
        system_prompt (Optional[str]): Optional system prompt for the LLM.
        enable_thinking (bool): Flag to enable or disable thinking functionality.

    Returns:
        None
    """

    # Ensure tools is a list of callables or valid tool definitions
    if not isinstance(tools, list):
        tools = []
    else:
        tools = [t for t in tools if callable(t) or isinstance(t, dict)]

    # Add system prompt if provided and different from the last system prompt
    if system_prompt:
        # Find the last system prompt in the message history
        last_system_prompt = None
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "system":
                last_system_prompt = messages[i].get("content")
                break

        # Only add a new system prompt if it's different from the last one
        if last_system_prompt != system_prompt:
            messages.append({"role": "system", "content": system_prompt})

    # Add user input to messages
    messages.append({"role": "user", "content": user_input})

    # Stream responses from the LLM
    client = ollama.Client()
    response: Iterator[ollama.ChatResponse] = client.chat(
        model=model,
        stream=True,
        messages=messages,
        tools=tools,
        think=enable_thinking
    )

    assistant_content = ""

    try:
        for chunk in response:
            if enable_thinking and chunk.message.thinking:
                print(chunk.message.thinking, end='', flush=True)
            if chunk.message.content:
                print(chunk.message.content, end='', flush=True)
                assistant_content += chunk.message.content
            if chunk.message.tool_calls:
                # Add any accumulated assistant content before tool calls
                if assistant_content:
                    messages.append({"role": "assistant", "content": assistant_content})
                    assistant_content = ""

                # Add assistant message with tool calls
                messages.append({
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"function": {"name": tc.function.name, "arguments": tc.function.arguments}} for tc in chunk.message.tool_calls]
                })

                for tool_call in chunk.message.tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = tool_call.function.arguments

                    # Print tool call
                    if tool_args:
                        if len(tool_args) == 1 and "kwargs" in tool_args:
                            # Handle wrapped kwargs
                            inner_args = tool_args["kwargs"]
                            if inner_args and isinstance(inner_args, dict):
                                args_str = ', '.join(f"{k}={v}" for k, v in inner_args.items())
                            else:
                                args_str = str(inner_args) if inner_args else ""
                        else:
                            args_str = ', '.join(f"{k}={v}" for k, v in tool_args.items())
                    else:
                        args_str = ""
                    print(f"\n  \033[90mtool call:\033[0m {tool_name}({args_str})")

                    # Find and execute the tool
                    for tool in tools:
                        if tool.__name__ == tool_name:
                            # Debug: print what we're actually passing to the tool
                            if ENABLE_DEBUG:
                                print(f"  \033[90mDEBUG: tool_args type={type(tool_args)}, content={tool_args}\033[0m")

                            # Debug: print the tool's input schema for problematic tools
                            if ENABLE_DEBUG and tool_name == "search_abstracts":
                                original_tool = None
                                for orig_tool in mcptools:
                                    if getattr(orig_tool, "name", None) == tool_name:
                                        original_tool = orig_tool
                                        break
                                if original_tool:
                                    print(f"  \033[90mDEBUG: {tool_name} input schema: {getattr(original_tool, 'inputs', 'N/A')}\033[0m")

                            tool_result = tool(**tool_args)

                            # Print tool results
                            print(f"  \033[90mtool results:\033[90m \033[0m")
                            print(f"{tool_result}")
                            print(f"  \033[90m/end of tool results\033[90m \033[0m\n")

                            # Add tool result to messages
                            messages.append({"role": "tool", "content": str(tool_result), "name": tool_name})

                # Continue streaming LLM responses after tool calls
                remaining_response = client.chat(
                    model=model,
                    stream=True,
                    messages=messages,
                    tools=tools,
                    think=enable_thinking
                )
                for remaining_chunk in remaining_response:
                    if remaining_chunk.message.content:
                        print(remaining_chunk.message.content, end='', flush=True)
                        assistant_content += remaining_chunk.message.content
    except KeyboardInterrupt:
        print("\n  \033[90m[Response Generation Cancelled]\033[0m")
        # Optionally, flush or clean up here

    # Add any remaining assistant content
    if assistant_content:
        messages.append({"role": "assistant", "content": assistant_content})

    return messages

# This function is just ass... needs work.
def parse_tool_arguments(inner_kwargs, param_names, input_keys):
    """
    Parse various formats of tool arguments into a proper kwargs dict.

    Args:
        inner_kwargs: The raw arguments from the LLM (string, dict, etc.)
        param_names: List of expected parameter names
        input_keys: Dict of parameter schemas from the tool

    Returns:
        dict: Parsed arguments ready for the tool
    """
    if ENABLE_DEBUG:
        print(f"  \033[90mDEBUG: parse_tool_arguments input: {inner_kwargs} (type: {type(inner_kwargs)})\033[0m")
        print(f"  \033[90mDEBUG: param_names: {param_names}\033[0m")

    # If it's already a dict, return it
    if isinstance(inner_kwargs, dict):
        if ENABLE_DEBUG:
            print(f"  \033[90mDEBUG: Processing dict input: {inner_kwargs}\033[0m")
        return inner_kwargs

    # If it's not a string, treat as single param
    if not isinstance(inner_kwargs, str):
        if ENABLE_DEBUG:
            print(f"  \033[90mDEBUG: Fallback to single param for non-dict/string: {inner_kwargs}\033[0m")
        if param_names:
            return {param_names[0]: inner_kwargs}
        else:
            return {}

    # String processing
    if not param_names:
        if ENABLE_DEBUG:
            print(f"  \033[90mDEBUG: No param_names, returning string as-is\033[0m")
        return {"value": inner_kwargs}

    # Try to parse as JSON if it looks like a dict (do this BEFORE key=value parsing)
    if (inner_kwargs.strip().startswith('{') and inner_kwargs.strip().endswith('}')):
        try:
            parsed = json.loads(inner_kwargs)
            if ENABLE_DEBUG:
                print(f"  \033[90mDEBUG: Parsed JSON string to dict: {parsed}\033[0m")
            return parsed
        except Exception as e:
            if ENABLE_DEBUG:
                print(f"  \033[90mDEBUG: Failed to parse JSON string: {e}\033[0m")
            # Try converting single quotes to double quotes for Python dict format
            try:
                fixed_json = inner_kwargs.replace("'", '"')
                parsed = json.loads(fixed_json)
                if ENABLE_DEBUG:
                    print(f"  \033[90mDEBUG: Parsed Python dict string to dict: {parsed}\033[0m")
                return parsed
            except Exception as e2:
                if ENABLE_DEBUG:
                    print(f"  \033[90mDEBUG: Failed to parse Python dict string: {e2}\033[0m")
                # Last resort: try using ast.literal_eval for Python dict strings
                try:
                    import ast
                    parsed = ast.literal_eval(inner_kwargs)
                    if isinstance(parsed, dict):
                        if ENABLE_DEBUG:
                            print(f"  \033[90mDEBUG: Parsed using ast.literal_eval: {parsed}\033[0m")
                        return parsed
                except Exception as e3:
                    if ENABLE_DEBUG:
                        print(f"  \033[90mDEBUG: Failed to parse with ast.literal_eval: {e3}\033[0m")

    # Try to parse key=value pairs from the string
    if '=' in inner_kwargs:
        if ENABLE_DEBUG:
            print(f"  \033[90mDEBUG: Detected key=value pairs in string: {inner_kwargs}\033[0m")

        # First try comma-separated pairs
        pairs = [v.strip() for v in inner_kwargs.split(',')]
        parsed = {}

        # If comma splitting doesn't work well, try space splitting
        if len(pairs) == 1 and ' ' in inner_kwargs:
            # Try to split by spaces while preserving key=value pairs
            import re
            # Match pattern like "key=value" including quoted values
            matches = re.findall(r'(\w+)=([^\s=]+)', inner_kwargs)
            if matches:
                parsed = {k: v for k, v in matches}
                if ENABLE_DEBUG:
                    print(f"  \033[90mDEBUG: Parsed space-separated key-value pairs: {parsed}\033[0m")
                return parsed

        # Fall back to comma-separated parsing
        for pair in pairs:
            if '=' in pair:
                k, v = pair.split('=', 1)
                parsed[k.strip()] = v.strip()

        if ENABLE_DEBUG:
            print(f"  \033[90mDEBUG: Parsed key-value pairs: {parsed}\033[0m")
        return parsed

    # Try splitting by comma first
    values = [v.strip() for v in inner_kwargs.split(",") if v.strip()]
    if ENABLE_DEBUG:
        print(f"  \033[90mDEBUG: Positional values after comma split: {values}\033[0m")

    # If not enough values, try splitting by space
    if len(values) != len(param_names):
        values = [v.strip() for v in inner_kwargs.split() if v.strip()]
        if ENABLE_DEBUG:
            print(f"  \033[90mDEBUG: Positional values after space split: {values}\033[0m")

    # If the number of values matches the number of param_names, map them
    if len(values) == len(param_names):
        try:
            mapped = {k: int(v) if input_keys and input_keys.get(k, {}).get('type') == 'integer' else v
                     for k, v in zip(param_names, values)}
        except Exception:
            mapped = {k: v for k, v in zip(param_names, values)}
        if ENABLE_DEBUG:
            print(f"  \033[90mDEBUG: Mapped positional args: {mapped}\033[0m")
        return mapped

    # Fallback: treat as single param
    if ENABLE_DEBUG:
        print(f"  \033[90mDEBUG: Fallback to single param for string: {inner_kwargs}\033[0m")
    if len(param_names) == 1:
        return {param_names[0]: inner_kwargs}
    else:
        return {param_names[0]: inner_kwargs}


def fn_adapter_mcp2ollama(mcptools, nativetools=None):
    """
    Adapts MCPAdapt tool objects to Ollama-compatible callables and adds any native callables.
    Each callable exposes the tool's name and description as function name and docstring.
    Handles single-argument tools by mapping kwargs to the expected input key.
    """
    adapted_tools = []
    def make_wrapper(tool):
        input_keys = getattr(tool, "inputs", None)
        param_names = list(input_keys.keys()) if input_keys and isinstance(input_keys, dict) else []
        def wrapper(**kwargs):
            # Handle case where LLM passes kwargs as a parameter
            if len(kwargs) == 1 and "kwargs" in kwargs:
                inner_kwargs = kwargs["kwargs"]
                if ENABLE_DEBUG:
                    print(f"  \033[90mDEBUG: Received kwargs wrapper: {inner_kwargs} (type: {type(inner_kwargs)})\033[0m")

                # Use the dedicated parsing function
                kwargs = parse_tool_arguments(inner_kwargs, param_names, input_keys)

            # If tool expects no inputs (like get_timestamp), ignore any kwargs
            if not input_keys or (isinstance(input_keys, dict) and len(input_keys) == 0):
                return tool.forward({})

            # If tool expects a single input, map any kwargs to the expected structure
            if input_keys and isinstance(input_keys, dict):
                if len(input_keys) == 1:
                    expected_key = param_names[0]
                    # If we get a single kwarg that's not the expected key, map it
                    if len(kwargs) == 1:
                        actual_key = list(kwargs.keys())[0]
                        if actual_key != expected_key:
                            kwargs = {expected_key: kwargs[actual_key]}

                # For multi-parameter tools, check if we need to wrap in a 'request' object
                if kwargs and "request" not in kwargs:
                    input_schema_str = str(input_keys)
                    if "request" in input_schema_str.lower():
                        if 'term' in input_schema_str.lower():
                            if len(kwargs) == 1:
                                value = list(kwargs.values())[0]
                                return tool.forward({"request": {"term": value}})
                            else:
                                return tool.forward({"request": kwargs})
                        else:
                            return tool.forward({"request": kwargs})

                return tool.forward(kwargs)

            return tool.forward(**kwargs)
        wrapper.__name__ = getattr(tool, "name", tool.__class__.__name__)
        wrapper.__doc__ = getattr(tool, "description", "No description available.")
        # Improved docstring: enumerate each parameter
        param_lines = []
        param_lines.append("\nGenerated Arg Info:)")
        if input_keys and isinstance(input_keys, dict) and len(input_keys) > 0:
            for k, v in input_keys.items():
                param_type = v.get('type', 'unknown') if isinstance(v, dict) else str(type(v))
                param_desc = v.get('description', '') if isinstance(v, dict) else str(v)
                param_lines.append(f"  {k} ({param_type}): {param_desc}")
        else:
            param_lines.append("\n  None")
        wrapper.__doc__ += "\n" + "\n".join(param_lines) + "\n----\n\n"
        ## DO NOT REMOVE.
        ## This is useful for debugging what the LLM recieves documentation-wise.
        # print("--------")
        # print(wrapper.__doc__)
        # print("--------")

        return wrapper
    for tool in mcptools:
        adapted_tools.append(make_wrapper(tool))
    # Add native tools if provided
    if nativetools:
        adapted_tools.extend(nativetools)
    return adapted_tools

def list_models():
    """List available Ollama models."""
    client = ollama.Client()
    return client.list()

def list_running_models():
    """List running Ollama processes."""
    client = ollama.Client()
    return client.ps()

def pull_model(model: str):
    """Pull a model from Ollama."""
    client = ollama.Client()
    return client.pull(model)

def set_debug_from_main(debug_flag):
    global ENABLE_DEBUG
    ENABLE_DEBUG = debug_flag
