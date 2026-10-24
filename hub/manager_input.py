"""Keep routine scheduling concise without truncating incoming messages."""

# A composition target, never a validation/truncation limit. Long originals pass through.
from .prompt_identity import VM_POLICY
from .git_workspaces import POLICY as GIT_POLICY

ROUTINE_TARGET=400
WAIT_POLICY='等待成员时结束本轮，成员汇报会唤醒你；仅需兜底检查时用schedule_wake设提醒后结束。禁止用sleep/Start-Sleep、循环轮询或占着工具等待成员。'
DELEGATION_POLICY='按任务匹配、忙闲、实际额度分工，不因DeepSeek或免费标签而默认偏向某个成员，未知额度不等于无限。允许成员充分执行，不凭数分钟未写文件就判卡死；先询问进展、看工具活动，给出合理等待时间，只有明确异常或必要抢占才强停。经理优先调度：实现、编译修错、打包和详细测试交给可用成员；自己做任务拆分、阻塞判断和验收。可快速诊断或小范围收尾，连续试错应转派。没有合适成员或任务难以拆分时，可说明原因后自行处理。'
POLICY=(
    '本轮为获批项目调度。新会话先用project_status(view="context")读取获批目标；详情按需查events。'
    '收到汇报即可调度，不等整批；详细检查交给成员，自己只判断结论。'
    +WAIT_POLICY+DELEGATION_POLICY+GIT_POLICY+VM_POLICY+
    '用project(progress,note)汇报整体完成百分比及依据；首次调度和里程碑变化时更新，按验收范围判断，不按轮次估算。'
    '仅在原授权内派工，不重派在途任务、不冲突改文件。普通补充信息用send(queue)；send(immediate)直接中断接收方当前轮次并优先处理新内容，仅在确需抢占时使用，不要随后误判为平台故障。可用project_queue查看、编辑、排序、删除待执行项，operation=interrupt直接打断并插入新内容；派工用project_assign并给write_paths（检查用read_paths，检查只读、直接汇报，不要求写报告文件）；独立worktree可并行，提交后由经理集成；共享目录勿冲突修改。停止成员任务用project_stop_task(task_id,reason)，可直接强停并立即改派；其他成员仍在执行时先等结束或强停，再用project_complete提交；演示以返回design_review_ready为准。'
    '单成员额度不足只等待该成员，继续派其它成员；不可因此暂停整个项目。用schedule_wake提醒自己或成员恢复，未知时间用time核查；只剩关键成员时加wait_for_agent自动等待，不靠用户续推。paused文字不是用户暂停指令。'
    '优先用MCP派工与结案，最终用简短Markdown正文汇报，不套JSON或代码围栏；自然语言不自动派工或结案。兼容JSON{"done":false,"report":"简短结论","tasks":[]}，工具派工后tasks=[]。'
)


def clip(text,limit):
    return text if len(text)<=limit else text[:limit-1]+'…'


def content(policy,notice):
    result=(policy+'\n\n' if policy else '')+notice
    return result
