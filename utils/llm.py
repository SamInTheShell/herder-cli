import ollama
from typing import List, Callable, Optional, Iterator

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


def fn_adapter_mcp2ollama(mcptools, nativetools=None):
    """
    Adapts MCPAdapt tool objects to Ollama-compatible callables and adds any native callables.
    Each callable exposes the tool's name and description as function name and docstring.
    Handles single-argument tools by mapping kwargs to the expected input key.
    """
    adapted_tools = []
    def make_wrapper(tool):
        input_keys = getattr(tool, "inputs", None)
        def wrapper(**kwargs):
            # Handle case where LLM passes kwargs as a parameter
            if len(kwargs) == 1 and "kwargs" in kwargs:
                inner_kwargs = kwargs["kwargs"]
                # If inner_kwargs is a string, it means LLM passed a positional argument
                # We need to map this to the expected parameter name
                if isinstance(inner_kwargs, str) and input_keys and isinstance(input_keys, dict):
                    if len(input_keys) == 1:
                        # Single parameter tool - check if it's a request wrapper
                        expected_key = list(input_keys.keys())[0]
                        if expected_key == "request":
                            # This is a request wrapper - need to check what goes inside
                            request_schema = input_keys["request"]
                            if isinstance(request_schema, dict) and "properties" in request_schema:
                                # Find the main parameter (usually 'term' for search)
                                props = request_schema["properties"]
                                if "term" in props:
                                    kwargs = {"request": {"term": inner_kwargs}}
                                elif "query" in props:
                                    kwargs = {"request": {"query": inner_kwargs}}
                                else:
                                    # Use the first required property
                                    required = request_schema.get("required", [])
                                    if required:
                                        kwargs = {"request": {required[0]: inner_kwargs}}
                                    else:
                                        kwargs = {"request": {list(props.keys())[0]: inner_kwargs}}
                            else:
                                kwargs = {expected_key: inner_kwargs}
                        else:
                            kwargs = {expected_key: inner_kwargs}
                    else:
                        # Multi-parameter tool - assume it's the first/main parameter
                        # For search_abstracts, this would typically be 'query' or 'term'
                        main_keys = ['query', 'term', 'search', 'q']  # Common search parameter names
                        for key in main_keys:
                            if key in input_keys:
                                kwargs = {key: inner_kwargs}
                                break
                        else:
                            # Fallback to first key if no common ones found
                            kwargs = {list(input_keys.keys())[0]: inner_kwargs}
                else:
                    kwargs = inner_kwargs if isinstance(inner_kwargs, dict) else {}

            # If tool expects no inputs (like get_timestamp), ignore any kwargs
            if not input_keys or (isinstance(input_keys, dict) and len(input_keys) == 0):
                return tool.forward({})

            # If tool expects a single input, map any kwargs to the expected structure
            if input_keys and isinstance(input_keys, dict):
                if len(input_keys) == 1:
                    expected_key = list(input_keys.keys())[0]
                    # If we get a single kwarg that's not the expected key, map it
                    if len(kwargs) == 1:
                        actual_key = list(kwargs.keys())[0]
                        if actual_key != expected_key:
                            kwargs = {expected_key: kwargs[actual_key]}

                # For multi-parameter tools, check if we need to wrap in a 'request' object
                # This handles cases like search_abstracts that expect {request: {term: "..."}}
                if kwargs and "request" not in kwargs:
                    # Check if the tool input schema mentions 'request'
                    input_schema_str = str(input_keys)
                    if "request" in input_schema_str.lower():
                        # For search_abstracts, we need to wrap in request object with 'term' key
                        if 'term' in input_schema_str.lower():
                            # Convert single value to {request: {term: value}}
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
