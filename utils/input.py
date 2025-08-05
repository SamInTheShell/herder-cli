from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.widgets import Frame, TextArea
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.shortcuts import clear
import sys

# This fucking input box needs work. -_-
# It's a temporary mockup of what is desired.

def input_box(prompt_text: str = "> ") -> str:
    bindings = KeyBindings()

    # Add a mode toggle for ENTER behavior
    enter_mode = {'submit': True}  # Default mode is submit

    @bindings.add('c-z')
    def _(event):
        event.app.current_buffer.text = ""  # Clear the text box
        event.app.current_buffer.reset()  # Reset the buffer to ensure clearing

    @bindings.add('c-c')
    def _(event):
        event.app.exit(exception=KeyboardInterrupt())

    @bindings.add('s-tab')
    def _(event):
        enter_mode['submit'] = not enter_mode['submit']  # Toggle the mode
        event.app.invalidate()  # Refresh the UI to reflect mode change

    @bindings.add('enter')
    def _(event):
        if enter_mode['submit']:
            event.app.exit(result=event.app.current_buffer.text)
        else:
            event.app.current_buffer.insert_text('\n')  # Create a new line

    text_area = TextArea(
        multiline=True,
        wrap_lines=True,
        scrollbar=False,
    )

    def get_help_text():
        return [
            ('class:helptext', f'   CTRL+Z to clear   |   CTRL+C to terminate   |   SHIFT+TAB to toggle ENTER mode ({"Submit" if enter_mode["submit"] else "New Line"})')
        ]

    help_window = Window(
        content=FormattedTextControl(text=get_help_text),
        height=1,
        align='RIGHT',
        dont_extend_height=True,
        style='bg:#1a1a1a fg:#888888',
    )

    def get_height():
        # Dynamically calculate the height based on the number of lines in the text area
        return max(text_area.document.line_count + 4, 5)  # Adjusted to grow for the label and spacing

    layout = Layout(
        HSplit([
            Window(
                content=FormattedTextControl(text="  Type your message below."),
                height=1,
                align="RIGHT",
                style="fg:#888888",  # Greyed out text
                dont_extend_height=True,
            ),
            Frame(
                body=HSplit([
                    text_area,
                    help_window
                ]),
                height=get_height,  # Ensure the height is dynamically calculated
            ),
            Window(height=1),
        ])
    )

    app = Application(
        layout=layout,
        key_bindings=bindings,
        full_screen=False,  # Inline mode, preserves prior output
        mouse_support=False,
        output=None,
        input=None,
    )

    try:
        result = app.run()
        # Calculate the actual height used by the layout for clearing
        box_height = get_height() + 2  # +2 for spacing windows above and below
        for _ in range(box_height):
            sys.stdout.write('\x1b[1A')  # Move cursor up
            sys.stdout.write('\x1b[2K')  # Clear line
        sys.stdout.flush()
        return result or ""
    except (KeyboardInterrupt, EOFError):
        box_height = get_height() + 2
        for _ in range(box_height):
            sys.stdout.write('\x1b[1A')
            sys.stdout.write('\x1b[2K')
        sys.stdout.flush()
        return None
