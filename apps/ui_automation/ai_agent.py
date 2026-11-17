import logging
import asyncio
import sys
from .ai_base import BaseBrowserAgent

logger = logging.getLogger('django')


def _run_async(coro):
    """在当前线程跑协程。Windows 上单独使用 Proactor 事件循环。

    Daphne 启动时会把进程策略改成 WindowsSelectorEventLoopPolicy。
    这种循环在 Windows 上不能创建子进程，browser-use 拉起 Chrome 时会抛出
    没有消息的 NotImplementedError。这里只给本次执行换循环，不改 Daphne 的全局策略。
    """
    if sys.platform == "win32":
        return asyncio.run(coro, loop_factory=asyncio.ProactorEventLoop)
    return asyncio.run(coro)

class BrowserAgent(BaseBrowserAgent):
    """
    Standard Browser Agent for Text Mode.
    Inherits all base functionality without applying dangerous visual patches.
    """
    def __init__(self, execution_mode='text', enable_gif=True, case_name=None):
        self.enable_gif = enable_gif
        self.case_name = case_name or "Adhoc Task"
        super().__init__(execution_mode='text')

# ============================================================================
# EXPORTED FUNCTIONS (FACTORY)
# ============================================================================

def get_agent_class(execution_mode='text'):
    # 始终返回文本模式实现
    return BrowserAgent

def run_ai_task_sync(task_description: str, planned_tasks=None, callback=None, should_stop=None, execution_mode='text'):
    agent = BrowserAgent(execution_mode='text')
    return _run_async(agent.run_task(task_description, planned_tasks, callback, should_stop))
    
def analyze_task_sync(task_description: str, execution_mode='text'):
    agent = BrowserAgent(execution_mode='text')
    return _run_async(agent.analyze_task(task_description))

def run_full_process_sync(task_description: str, analysis_callback=None, step_callback=None, should_stop=None, execution_mode='text', enable_gif=True, case_name=None):
    logger.info(f"DEBUG: Entering run_full_process_sync with execution_mode=text, enable_gif={enable_gif}")

    agent = BrowserAgent(execution_mode='text', enable_gif=enable_gif, case_name=case_name)

    logger.info(f"DEBUG: Agent created successfully ({type(agent).__name__}), starting asyncio.run")
    return _run_async(agent.run_full_process(task_description, analysis_callback, step_callback, should_stop))
