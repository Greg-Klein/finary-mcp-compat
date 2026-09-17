"""Read-only live discovery check; never invokes financial tools or prints data."""
import argparse
import asyncio
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def check(config: str):
    params = StdioServerParameters(command=sys.executable, args=[
        str(Path(__file__).with_name("finary_compat.py")), "--config", config])
    async with asyncio.timeout(45):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                first = await session.list_tools()
                second = await session.list_tools()
                assert [t.name for t in first.tools] == [t.name for t in second.tools]
                tools = {t.name: t.model_dump(by_alias=True) for t in first.tools}
                for name in ("get_budget_overview", "search_spending"):
                    assert tools[name]["outputSchema"]["type"] == "object"
                print(f"PASS: protocol={session.protocol_version}, tools={len(first.tools)}, "
                      "two discovery calls validated by the unmodified SDK.")
    print("PASS: session closed; no financial tools called.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    asyncio.run(check(parser.parse_args().config))
