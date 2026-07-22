---
description: Connect this machine to your memory server using the connection string it printed.
argument-hint: <connection-string>
allowed-tools: Bash(python3 "${CLAUDE_PLUGIN_ROOT}/bin/setup.py":*)
---

Run this exact command, passing the user's argument through unchanged:

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/setup.py" '$ARGUMENTS'
```

Then report what it printed, in one or two lines.

If it says the connection string could not be read, tell the user to start
their memory server and copy the `memory://...` line it prints on startup. Do
not try to guess or reconstruct the string yourself, and never ask them to
paste the raw token into the chat if the connection string form is available.

If no argument was given, the script reports whether this machine is already
configured. Relay that.
