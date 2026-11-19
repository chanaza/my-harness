# Genspark adapter

Genspark has no export and no public API, so it saves itself through the
[harness connector](../connector.md), exactly like the Claude account: the adapter only
adds what is particular to Genspark (its Hubs are projects, its pages and slides are
apps, where its custom instructions live). The saving and reading instructions are the
engine's (`harness/templates/connector/`), the same for every such tool.

Setting up (once per Genspark account):

1. `python -m harness setup genspark` names the account (its e-mail) and prints the
   instruction line for it.
2. In Genspark: add an MCP server (Streamable HTTP) with your connector's address.
3. In Genspark, Settings > Personalization: add the instruction line. From then on every
   exchange is saved word for word, a summary every 10 replies, and "describe my Genspark
   to the harness" saves what the account has built.

Not verified yet in Genspark itself: adding the MCP server, and how reliably it follows
the instruction after every reply (the log marks any reply that did not arrive).
