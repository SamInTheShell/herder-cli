# Herder
A terminal chat utility for Ollama providing MCP support.

![Screenshot](screenshot.png)

This also supports running without an input prompt, which makes scheduling a task easy with [crons](https://en.wikipedia.org/wiki/Cron).
```shell
# uv run main.py --prompt 'What is my name.' --history-file history.log --no-banner
  User (2025-08-04T21:24:11.752604):
What is my name.

  Assistant (2025-08-04T21:24:11.752625):
I'm sorry, but I don't have access to personal information about users, including names. Is there something else I can help you with?

# uv run main.py --prompt 'We are doing a memory test. The name is Sam.' --history-file history.log --no-banner
  User (2025-08-04T21:24:18.671558):
We are doing a memory test. The name is Sam.

  Assistant (2025-08-04T21:24:18.671572):
Thank you for letting me know! If you have any other questions or need assistance with anything else, feel free to ask.

# uv run main.py --prompt 'What was my name?' --history-file history.log --no-banner
  User (2025-08-04T21:24:24.214079):
What was my name?

  Assistant (2025-08-04T21:24:24.214095):
Your name is Sam.

```

## Working Features
- Chatting with Ollama models.
- MCP server configuration.
- Tool calling.

## Features in Progress
- Tool call approval confirmation.
- Autoapprove options/configuration.
- Default tools: Sandboxed file access, Command calling
- Automatic context compaction.

## Nice Haves
- Would be great to figure out how to support shrinking the message box on terminal resize.
