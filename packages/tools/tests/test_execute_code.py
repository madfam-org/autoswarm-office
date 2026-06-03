import os

import pytest

from selva_tools.execute_code import ExecuteCodeTool


@pytest.mark.asyncio
async def test_execute_python_basic():
    tool = ExecuteCodeTool()
    result = await tool.execute(code="print('hello world')", language="python")
    assert result.success is True
    assert "hello world" in result.output


@pytest.mark.asyncio
async def test_execute_bash_basic():
    tool = ExecuteCodeTool()
    result = await tool.execute(code="echo 'hi from bash'", language="bash")
    assert result.success is True
    assert "hi from bash" in result.output


@pytest.mark.asyncio
async def test_execute_code_block_dangerous():
    # Set policy to block
    os.environ["SELVA_EXEC_POLICY"] = "block"
    tool = ExecuteCodeTool()
    # Pattern: rm -rf
    result = await tool.execute(code="import os; os.system('rm -rf /')", language="python")
    assert result.success is False
    assert "Execution blocked" in result.error


@pytest.mark.asyncio
async def test_execute_timeout():
    tool = ExecuteCodeTool()
    # Code that sleeps longer than timeout
    result = await tool.execute(code="import time; time.sleep(2)", timeout=0.1)
    assert result.success is False
    assert "timed out" in result.error


@pytest.mark.asyncio
async def test_output_truncation():
    tool = ExecuteCodeTool()
    # Code that prints more than 10KB
    long_str = "x" * 12000
    result = await tool.execute(code=f"print('{long_str}')")
    assert result.success is True
    assert len(result.output) <= 10240 + 50
    assert "[... output truncated ...]" in result.output
