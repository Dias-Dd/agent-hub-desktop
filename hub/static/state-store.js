/**
 * HubStateStore - 前端状态归一化 Store 与面板 Action 调度器
 * 核心功能：
 *   1. 1.5s 防重叠轮询与请求序号防串项目机制
 *   2. 断网或报错时保留最后一次有效快照并标记“连接中断/数据过期”，绝不清空全部空闲
 *   3. 4 类 ID 严格映射（projects, workflows, planning + revision, runs）
 *   4. 9 宫格卡片标准数据结构与共享额度归一化（如 sol-1/sol-2/astra 共享 OpenAI 窗口）
 *   5. 双聊天流拆分：与项目经理沟通（含 planning 审批门禁）与 Agent 群聊与动态
 *   6. 封装全部用户面板 Action，严格校验参数与分流，防重发复用 request_key
 *   7. CSP 兼容与 textContent 安全渲染辅助
 */

'use strict';

const ALL_AGENT_IDS = [
  'deepseek-4',
  'deepseek-1',
  'deepseek-2',
  'deepseek-3',
  'deepseek-5',
  'deepseek-6',
  'deepseek-7',
  'deepseek-8',
  'deepseek-9'
];

const DEFAULT_AGENT_METAS = {
  'deepseek-4': { model: 'DeepSeek Flash', defaultRole: '项目经理', provider: 'deepseek' },
  'deepseek-1': { model: 'DeepSeek Flash', defaultRole: '后端工程师', provider: 'deepseek' },
  'deepseek-2': { model: 'DeepSeek Flash', defaultRole: '前端工程师', provider: 'deepseek' },
  'deepseek-3': { model: 'DeepSeek Flash', defaultRole: '测试工程师', provider: 'deepseek' },
  'deepseek-5': { model: 'DeepSeek Flash', defaultRole: '架构与审查', provider: 'deepseek' },
  'deepseek-6': { model: 'DeepSeek Flash', defaultRole: '实现工程师', provider: 'deepseek' },
  'deepseek-7': { model: 'DeepSeek Flash', defaultRole: '可靠性工程师', provider: 'deepseek' },
  'deepseek-8': { model: 'DeepSeek Flash', defaultRole: '技术负责人', provider: 'deepseek' },
  'deepseek-9': { model: 'DeepSeek Flash', defaultRole: '备用工程师', provider: 'deepseek' }
};

class HubStateStore {
  /**
   * @param {Object} options
   * @param {HubApiClient} options.client - HubApiClient 实例
   * @param {number} [options.pollIntervalMs=1500] - 轮询间隔，默认 1.5s
   */
  constructor(options = {}) {
    if (!options.client) {
      throw new Error('HubStateStore 初始化必须传入 HubApiClient 实例');
    }
    this.client = options.client;
    this.pollIntervalMs = options.pollIntervalMs || 1500;

    // 状态容器：保留最后一次有效快照
    this.rawState = null;
    this.connectionStatus = 'initial'; // 'initial' | 'connected' | 'disconnected' | 'error'
    this.connectionMessage = '未连接';
    this.isStale = false;
    this.lastUpdated = null;
    this.lastError = null;

    // 内部轮询控制
    this._isRunning = false;
    this._isPolling = false;
    this._pollTimer = null;
    this._currentPollSeq = 0;
    this._selectedDiscussionId = null;

    // 订阅者监听器
    this._subscribers = new Set();
  }

  // --- 订阅与通知 ---

  subscribe(callback) {
    if (typeof callback !== 'function') {
      throw new Error('订阅者必须为回调函数');
    }
    this._subscribers.add(callback);
    // 立即以当前快照通知一次
    try {
      callback(this.getNormalizedState());
    } catch (e) {
      console.error('Subscriber callback error:', e);
    }
    return () => {
      this._subscribers.delete(callback);
    };
  }

  _notify() {
    const normalized = this.getNormalizedState();
    for (const callback of this._subscribers) {
      try {
        callback(normalized);
      } catch (e) {
        console.error('Subscriber error during notify:', e);
      }
    }
  }

  // --- 轮询引擎 (1.5s 防重叠、防串项目、断网保留快照) ---

  startPolling() {
    if (this._isRunning) return;
    this._isRunning = true;
    this.refresh();
  }

  stopPolling() {
    this._isRunning = false;
    if (this._pollTimer) {
      clearTimeout(this._pollTimer);
      this._pollTimer = null;
    }
  }

  /**
   * 切换当前项目：重置请求序号，使在途过期响应自动被丢弃，并触发刷新
   * @param {string} projectId - 项目分组 ID
   */
  async switchProject(projectId) {
    const newSeq = this.client.setSelectedProjectId(projectId);
    this._currentPollSeq = newSeq;
    this._selectedDiscussionId = null;
    await this.refresh(true);
  }

  /**
   * 执行一次状态拉取
   * @param {boolean} [immediate=false] - 是否无视正在轮询标志立即开始（项目切换等显式操作）
   */
  async refresh(immediate = false) {
    if (this._isPolling && !immediate) {
      return;
    }

    if (this._pollTimer) {
      clearTimeout(this._pollTimer);
      this._pollTimer = null;
    }

    this._isPolling = true;
    const pollSeq = this.client.getCurrentPollSeq();
    const activeProject = this.client.getSelectedProjectId();

    try {
      const snapshot = await this.client.getState({
        seq: pollSeq,
        expectedProjectId: activeProject
      });

      // 成功获得新快照：更新状态与时间戳
      this.rawState = snapshot;
      this.connectionStatus = 'connected';
      this.connectionMessage = '已连接 · 数据正常';
      this.isStale = false;
      this.lastUpdated = Date.now();
      this.lastError = null;

      // 如果未指定 selectedDiscussionId，自动选中第一条
      if (!this._selectedDiscussionId && snapshot.planning && snapshot.planning.length > 0) {
        this._selectedDiscussionId = snapshot.planning[0].id;
      }

      this._notify();
    } catch (err) {
      // 若是因切换项目主动丢弃的过期响应，静默忽略
      if (err.discarded || err.name === 'StaleResponseError') {
        return;
      }

      // 断网或请求报错：保留最后一次有效快照，标记为“连接中断/数据过期”，绝不清空！
      this.connectionStatus = 'disconnected';
      this.connectionMessage = '连接中断/数据过期';
      this.isStale = true;
      this.lastError = err.message || '网络连接异常';

      this._notify();
    } finally {
      this._isPolling = false;
      if (this._isRunning) {
        // Concurrent explicit refreshes share one next poll, never multiply timers.
        if (this._pollTimer) clearTimeout(this._pollTimer);
        this._pollTimer = setTimeout(() => {
          this.refresh();
        }, typeof document !== 'undefined' && document.hidden ? Math.max(15000,this.pollIntervalMs) : !this.rawState || [this.rawState?.codex?.runs,this.rawState?.antigravity?.runs,this.rawState?.deepseek?.runs,this.rawState?.integration_runs].some(runs=>(runs||[]).some(r=>['queued','running','interrupting'].includes(r.status)))?this.pollIntervalMs:Math.max(5000,this.pollIntervalMs));
      }
    }
  }

  // --- 4 类 ID 严格映射与校验 ---

  /**
   * 获取系统中当前所有 4 类 ID 的标准映射结构
   */
  getIdMapping() {
    const state = this.rawState || {};
    const projects = state.projects || [];
    const workflows = state.workflows || [];
    const plannings = state.planning || [];

    // 汇集三类 provider 的执行记录 run_id
    const runMap = new Map();
    const collectRuns = (runs = [], provider) => {
      for (const r of runs) {
        if (r && r.id) {
          runMap.set(r.id, {
            id: r.id,
            provider,
            agent: r.agent,
            status: r.status,
            taskId: r.task_id || null,
            messageId: r.source_message_id || r.message_id || null
          });
        }
      }
    };

    collectRuns(state.codex?.runs, 'codex');
    collectRuns(state.antigravity?.runs, 'antigravity');
    collectRuns(state.deepseek?.runs, 'deepseek');
    for(const r of state.integration_runs||[])collectRuns([r],r.provider);

    return {
      // 1. 项目分组 ID
      projects: projects.map(p => ({ id: p.id, name: p.name, cwd: p.cwd })),
      selectedProjectId: this.client.getSelectedProjectId(),

      // 2. 工作流 ID
      workflows: workflows.map(w => ({
        id: w.id,
        status: w.status,
        phase: w.phase,
        manager: w.manager || this.rawState?.selected_manager || null,
        requirement: w.requirement
      })),
      activeWorkflowId: workflows.find(w => ['active', 'needs_attention', 'paused'].includes(w.status))?.id || null,

      // 3. 讨论 ID 与 Revision
      plannings: plannings.map(pl => ({
        id: pl.id,
        revision: pl.revision,
        state: pl.state,
        workflowId: pl.workflow_id || null
      })),
      latestPlanningRevision: plannings[0]?.revision ?? null,

      // 4. 执行 ID (带归属 provider)
      runs: Array.from(runMap.values())
    };
  }

  resolveRunProvider(runId) {
    if (!runId) return null;
    const mapping = this.getIdMapping();
    const item = mapping.runs.find(r => r.id === runId)||this.rawState?.integration_runs?.find(r=>r.id===runId);
    return item ? item.provider : null;
  }

  // --- 9 宫格卡片标准数据结构与共享额度归一化 ---

  getNormalizedAgents() {
    const state = this.rawState;
    if (!state) return [];

    const realAgentsSet = new Set(state.real_agents || []);
    const stops = state.coordination?.stops || [];
    const tasks = state.tasks || [];

    // 收集所有 provider 的 active runs
    const allActiveRuns = [];
    const checkRuns = (runs = [], provider) => {
      for (const r of runs) {
        if (r && ['queued', 'running', 'waiting_quota', 'interrupting'].includes(r.status)) {
          allActiveRuns.push({ ...r, provider });
        }
      }
    };
    checkRuns(state.codex?.runs, 'codex');
    checkRuns(state.antigravity?.runs, 'antigravity');
    checkRuns(state.deepseek?.runs, 'deepseek');
    for(const r of state.integration_runs||[])checkRuns([r],r.provider);

    const agentList = state.agents || [];
    const agentMap = new Map();
    for (const a of agentList) {
      agentMap.set(a.id, a);
    }

    return (state.integrations ? state.agents.map(a=>a.id) : ALL_AGENT_IDS).map(id => {
      const a = agentMap.get(id) || { id, role: DEFAULT_AGENT_METAS[id]?.defaultRole, status: 'offline' };
      const meta = DEFAULT_AGENT_METAS[id] || {};
      const isReal = realAgentsSet.has(id);

      // 停止锁检测 (agent === '*' 或 agent === id)
      const stopLock = stops.find(s => s.agent === '*' || s.agent === id);
      const isStopped = Boolean(stopLock);

      // 归一化状态判断
      let status = a.status || 'idle';
      let displayStatus = '空闲';

      if (isStopped) {
        status = 'stopped';
        displayStatus = '已紧急停止';
      } else if (isReal && !a.active) {
        status = 'standby';
        displayStatus = '待命 · 按需启动';
      } else {
        const labelMap = { idle: '空闲', busy: '忙碌', offline: '离线' };
        displayStatus = labelMap[status] || status;
      }

      // 关联正在进行中的任务
      const agentTasks = tasks
        .filter(t => t.agent === id && !['done','cancelled'].includes(t.status))
        .map(t => ({
          id: t.id,
          title: t.title,
          progress: t.progress || 0,
          status: t.status,
          note: t.note || ''
        }));

      // 关联正在进行中的执行 Run
      const agentRuns = allActiveRuns
        .filter(r => r.agent === id)
        .map(r => ({
          id: r.id,
          status: r.status,
          prompt: r.prompt || '',
          provider: r.provider
        }));

      const profile=a.profile,connection=state.integrations?.connections.find(c=>c.id===profile?.connection_id);
      const quotaStatus=state.integrations?.agents.find(x=>x.id===id)?.quota_status;
      const quotaExhausted=quotaStatus?.exhausted===true;
      const modelUnavailable=state.integrations?.agents.find(x=>x.id===id)?.model_status||null;
      if(quotaExhausted){displayStatus='额度耗尽';}if(modelUnavailable){displayStatus='模型不可用';}
      const sharedQuota = {
        groupId:connection?.id||'deepseek_api',groupName:connection?.name||'DeepSeek 官方 API · 平台不限额',
        sharedWith:connection?state.integrations.agents.filter(a=>a.enabled&&a.connection_id===connection.id).map(a=>a.id):[...ALL_AGENT_IDS],remainingRuns:null,remainingCents:null,
        reservedCents:state.deepseek?.reserved_cents || 0,budgetCents:null,windows:connection?.quota?.remaining!=null?[{name:connection.name,remainingPercent:connection.quota.remaining,resetsAtFormatted:connection.quota.resets_at?new Date(connection.quota.resets_at*1000).toLocaleString():'未知',source:connection.quota.source}]:[]
      };

      return {
        id,
        name: profile?.name||id,
        role: a.role || meta.defaultRole || '工程师',
        model: a.model || meta.model || '官方模型',
        status,
        displayStatus,
        quotaExhausted,
        modelUnavailable,
        isStopped,
        stopReason: stopLock?.reason || null,
        isRealAgent: isReal,
        heartbeat: a.heartbeat || null,
        heartbeatFormatted: this._formatTime(a.heartbeat),
        activeTasks: agentTasks,
        activeRuns: agentRuns,
        provider: profile?.connection_id==='deepseek-default'?'deepseek':profile?'integration:'+profile.connection_id:meta.provider||'unknown',
        sharedQuota,
        manualQuota: {
          remaining: a.quota?.remaining ?? null,
          resets_at: a.quota?.resets_at ?? null,
          source: a.quota?.source || 'unknown',
          recovery: a.quota?.recovery || null
        }
      };
    });
  }

  // --- 双聊天流拆分 ---

  /**
   * 数据源 1：「与项目经理沟通」
   * 包含 planning[] 讨论流、最新 revision 审批门禁、动态读取的 workflow.manager 汇报
   */
  isTaskEnvelope(message) {
    if(message.origin==='platform_task')return true;
    const match=/^\[task:([a-f0-9]{32})\] /.exec(message.body||'');
    return !!match&&(this.rawState?.tasks||[]).some(task=>task.id===match[1]);
  }

  getManagerDiscussionStream() {
    const state = this.rawState || {};
    const workflows = state.workflows || [];
    const activeWorkflow = workflows.find(w => ['active', 'needs_attention', 'paused'].includes(w.status)) || workflows[0] || null;

    // 动态读取当前经理，跟随项目配置
    const currentManager = state.selected_manager || activeWorkflow?.manager || state.planning?.[0]?.manager || (state.agents||[]).find(a=>a.role==='项目经理')?.id || state.agents?.[0]?.id || null;

    // 获取当前讨论会话
    const plannings = state.planning || [];
    const currentDiscussion = (this._selectedDiscussionId && plannings.find(p => p.id === this._selectedDiscussionId)) || plannings[0] || null;

    // 审批门禁状态判断
    const isAwaitingApproval = currentDiscussion?.state === 'awaiting_approval';
    const currentRevision = currentDiscussion?.revision ?? null;
    const canApprove = isAwaitingApproval && currentRevision !== null;

    const managerRuns = [...['deepseek','codex','antigravity'].flatMap(provider=>state[provider]?.runs||[]),...(state.integration_runs||[])];
    const historyTime = (message,index) => {
      if(message.created)return message.created;
      const run=managerRuns.find(r=>r.id===message.run_id);
      if(run)return run.finished||run.created||null;
      if(message.role==='user') {
        const next=(currentDiscussion?.history||[]).slice(index+1).find(m=>m.run_id);
        const request=managerRuns.find(r=>r.id===(next?.run_id||currentDiscussion?.pending));
        if(request)return request.created||null;
        if(index===0)return currentDiscussion?.created||null;
      }
      return null;
    };
    // 格式化讨论历史消息
    const discussionInputs=[...(state.messages||[]),...(state.manager_messages||[])].filter(m=>m.discussion_session_id===currentDiscussion?.id);
    const history = (currentDiscussion?.history || []).map((m, idx) => ({
      id: `plan_msg_${idx}`,
      role: m.role, // 'user' 或 manager
      senderName: m.role === 'user' ? '用户 (你)' : `${currentManager.toUpperCase()}${m.revision ? ` · 计划 v${m.revision}` : ''}`,
      text: m.text || '',
      revision: m.revision || null,
      isUser: m.role === 'user',
      sourceMessageId:m.message_id,
      timestamp: historyTime(m,idx),
      inputRun: m.role==='user' ? (m.input_run_id||(currentDiscussion.history.slice(idx+1).find(x=>x.run_id)?.run_id)||currentDiscussion.pending) : null
    })).filter(m=>!(m.isUser&&discussionInputs.some(d=>(m.sourceMessageId&&d.id===m.sourceMessageId)||(m.inputRun&&d.discussion_run_id===m.inputRun&&d.body===m.text))));

    if (history.length === 0 && activeWorkflow && !(currentDiscussion?.history||[]).length) {
      if (activeWorkflow.requirement) {
        history.push({
          id: 'wf_req',
          role: 'user',
          senderName: '用户 (你)',
          text: activeWorkflow.requirement,
          revision: null,
          isUser: true,
          timestamp: activeWorkflow.created || null
        });
      }
      if (activeWorkflow.report) {
        history.push({
          id: 'wf_rep',
          role: 'manager',
          senderName: currentManager.toUpperCase(),
          text: activeWorkflow.report,
          revision: null,
          isUser: false,
          timestamp: null
        });
      }
    }

    // 汇集与当前经理直接对话的用户消息，按 created 升序排列
    const projectManagers=new Set([currentManager,...workflows.map(w=>w.manager),...plannings.map(p=>p.manager)].filter(Boolean));
    const discussionReplyRuns=new Set((currentDiscussion?.history||[]).filter(m=>m.role!=='user'&&m.run_id).map(m=>m.run_id));
    const replyKeys=new Set([...(state.messages||[]),...(state.manager_messages||[])].filter(m=>m.recipient==='user').map(m=>m.request_key));
    const repliedInputs=new Set(managerRuns.filter(r=>replyKeys.has('execution:'+r.id+':user')).map(r=>r.message_id).filter(Boolean));
    const userDirectMessages = [...new Map([...(state.messages||[]),...(state.manager_messages||[])].map(m=>[m.id,m])).values()]
      .filter(m => !this.isTaskEnvelope(m)&&((m.sender === 'user' && projectManagers.has(m.recipient)) ||
                   (projectManagers.has(m.sender) && m.recipient === 'user')))
      .filter(m=>{
        const receipt=/^execution:([^:]+):user$/.exec(m.request_key||'');
        return !(m.recipient==='user'&&receipt&&discussionReplyRuns.has(receipt[1]));
      })
      .sort((a, b) => (a.created || 0) - (b.created || 0))
      .map(m => ({
        id: m.id,
        role: m.sender === 'user' ? 'user' : 'manager',
        senderName: m.sender === 'user' ? '用户 (你)' : m.sender,
        text: m.body,
        // Discussion replies belong to manager history/live output, never under the user's bubble.
        result: m.discussion_session_id || (m.sender==='user'&&repliedInputs.has(m.id)) ? null : (m.result || null),
        status: m.status,
        timestamp: m.created,
        timestampFormatted: this._formatTime(m.created),
        isUser: m.sender === 'user'
      }));

    const fallback=history.findIndex(m=>m.id==='wf_req');
    if(fallback>=0&&userDirectMessages.some(m=>m.isUser&&m.text===history[fallback].text&&Math.abs((m.timestamp||0)-(history[fallback].timestamp||0))<5))history.splice(fallback,1);
    return {
      manager: currentManager,
      workflow: activeWorkflow ? {
        id: activeWorkflow.id,
        status: activeWorkflow.status,
        phase: activeWorkflow.phase,
        report: activeWorkflow.report || '暂无工作流汇报',
        callsUsed: activeWorkflow.calls_used ?? activeWorkflow.steps?.length ?? 0,
        maxCalls: activeWorkflow.max_calls,
        expires: activeWorkflow.expires,
        patrolled: activeWorkflow.patrolled
      } : null,
      planning: currentDiscussion ? {
        sessionId: currentDiscussion.id,
        revision: currentRevision,
        state: currentDiscussion.state,
        mode: currentDiscussion.mode || 'planning',
        stateLabel: {
          chatting: '与经理对齐需求，准备好后点击开始计划',
          designing: '产品演示阶段，确认最终设计后才正式制作',
          thinking: `${currentManager} 正在分析讨论需求`,
          draft: '待完善需求，尚未形成可执行计划',
          awaiting_approval: '计划草案已就绪，等待你确认批准',
          executing: '已确认计划，任务正在执行中',
          error: '本轮讨论失败或未通过校验'
        }[currentDiscussion.state] || currentDiscussion.state,
        error: currentDiscussion.error || null,
        pending: Boolean(currentDiscussion.pending),
        planDraft: currentDiscussion.plan || null,
        options: currentDiscussion.options || null,
        isAwaitingApproval,
        canApprove
      } : null,
      history,
      userDirectMessages
    };
  }

  /**
   * 数据源 2：「Agent 群聊与动态」
   * 包含 Agent 间对话、Agent 与经理对话、coordination.wakeups/reports
   */
  getAgentActivityStream() {
    const state = this.rawState || {};
    const messages = state.messages || [];
    const coordination = state.coordination || {};
    const wakeups = coordination.wakeups || [];
    const reports = coordination.reports || [];


    const timeline = [], representedReports=new Set();
    const manager=this.getManagerDiscussionStream().manager;

    // 1. Agent 间及汇报消息（排除普通用户与经理讨论）
    for (const m of messages) {
      const platformNotice=m.sender==='平台'&&/^(?:\[task:[a-f0-9]{32}\] )?(?:平台通知：|成员执行已结束。请核查)/.test(m.body||'');
      if(this.isTaskEnvelope(m)&&m.recipient===manager&&!platformNotice)continue;
      if (m.sender === 'user' && m.recipient !== '*' && !this.isTaskEnvelope(m)) {
        // 用户单聊经理已在 stream 1 展现，广播或 Agent 间在此展现
        continue;
      }
      let body=platformNotice?String(m.body||'').replace(/^\[task:[a-f0-9]{32}\] /,''):m.body,prompt=m.prompt||null;
      if(String(body||'').startsWith('[主动汇报] ')){
        try{const report=JSON.parse(body.slice(7));if(report.run)representedReports.add(report.run);prompt=body;body=String(report.summary||'')+'\n风险：'+(report.risk||'unknown')+(report.evidence?.length?'\n证据：'+report.evidence.join('；'):'');}catch{}
      }
      if(m.delivery_reason)body+='\n等待原因：'+m.delivery_reason;
      timeline.push({
        id: m.id,
        category: 'message',
        timestamp: m.created || 0,
        timestampFormatted: this._formatTime(m.created),
        title: `${platformNotice?'平台':this.isTaskEnvelope(m)?'平台调度':m.sender} → ${m.recipient}`,
        body,
        prompt,
        result: platformNotice||String(m.body||'').startsWith('[主动汇报] ')?null:m.result || null,
        status: m.status,
        meta: `模式: ${m.mode} · 尝试: ${m.attempts || 1}`
      });
    }

    // 2. 唤醒日志 (wakeups)
    for (const [idx, w] of wakeups.entries()) {
      if(['batched','queued','completed'].includes(w.status)||messages.some(m=>m.id===w.message))continue;
      timeline.push({
        id: `wake_${idx}_${w.created || idx}`,
        category: 'wakeup',
        timestamp: w.created || 0,
        timestampFormatted: this._formatTime(w.created),
        title: `唤醒调度 · ${w.status}`,
        body: w.note || '',
        meta: `唤醒深度: ${w.depth}`
      });
    }

    // 3. 执行简报与风险评估 (reports)
    for (const [idx, r] of reports.entries()) {
      if(representedReports.has(r.run))continue;
      timeline.push({
        id: `report_${idx}_${r.created || idx}`,
        category: 'report',
        runId: r.run || null,
        timestamp: r.created || 0,
        timestampFormatted: this._formatTime(r.created),
        title: `执行简报 · [${r.risk || 'unknown'}] · Run ${r.run || 'unknown'}`,
        body: r.summary || '',
        meta: `证据: ${r.evidence || '无'} · 风险自评: ${r.risk || '未标注'}`
      });
    }

    // Platform notifications are visible here as well as in the reminder panel.
    for(const notice of state.pending_notifications||[]){
      if(messages.some(m=>m.body===notice.body&&m.sender===notice.source))continue;
      timeline.push({id:'notice_'+notice.id,category:'notification',timestamp:notice.created||0,timestampFormatted:this._formatTime(notice.created),title:(notice.source||'平台')+' → '+(notice.recipient||'当前经理'),body:notice.body||'',status:notice.state,meta:notice.category||'平台通知'});
    }

    // 按时间戳倒序排列（最新的在最前）
    timeline.sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0));

    return {
      timeline,
      totalCount: timeline.length
    };
  }

  /**
   * 汇总获取归一化视图数据
   */
  getNormalizedState() {
    return {
      connection: {
        status: this.connectionStatus,
        message: this.connectionMessage,
        isStale: this.isStale,
        lastUpdated: this.lastUpdated,
        lastError: this.lastError
      },
      idMapping: this.getIdMapping(),
      agents: this.getNormalizedAgents(),
      managerStream: this.getManagerDiscussionStream(),
      agentStream: this.getAgentActivityStream(),
      rawSnapshot: this.rawState
    };
  }

  // --- 封装全部用户面板 Action 调用函数 ---

  /**
   * 创建新项目分组
   * @param {string} name - 项目名称
   */
  async createProject(name) {
    const result = await this.client.postAction('project_create', { name: name?.trim() });
    await this.switchProject(result.id);
    return result;
  }

  /**
   * 与项目经理进行计划讨论 (plan_chat)
   */
  async sendPlanChat({ body, options, sessionId = null, confirmed = false, startPlanning = false }) {

    const args = {
      body: body?.trim(),
      confirmed: Boolean(confirmed),
      start_planning: Boolean(startPlanning)
    };

    if (sessionId) {
      args.session_id = sessionId;
      const discussion = (this.rawState?.planning || []).find(p => p.id === sessionId);
      if (discussion && discussion.revision !== undefined) {
        args.revision = discussion.revision;
      }
    }
    if (options) {
      args.options = options;
    }

    const result = await this.client.postAction('plan_chat', args);
    if (result && result.id) {
      this._selectedDiscussionId = result.id;
    }
    await this.refresh(true);
    return result;
  }

  /**
   * 严格批准门禁：用户显式动作触发批准计划
   * 必须携带当前最新 revision 和文本 "按计划执行"
   */
  async approvePlan({ sessionId, revision, options }) {

    // 校验 revision 是否与当前讨论草案最新版本一致
    const currentDiscussion = (this.rawState?.planning || []).find(p => p.id === sessionId);
    if (currentDiscussion && currentDiscussion.revision !== revision) {
      throw new Error(`当前计划已被更新至 v${currentDiscussion.revision}，不能批准过期的 v${revision}，请刷新审阅后再确认`);
    }

    // 严格限制正文必须为 "按计划执行"
    const args = {
      session_id: sessionId,
      revision: revision,
      body: '按计划执行',
      options: options || currentDiscussion?.options || null
    };

    const result = await this.client.postAction('plan_chat', args);
    await this.refresh(true);
    return result;
  }

  /**
   * 重新读取已完成但未校验通过的计划草案 (plan_recover)
   */
  async recoverPlan(sessionId) {
    const result = await this.client.postAction('plan_recover', { session_id: sessionId });
    await this.refresh(true);
    return result;
  }

  /**
   * 停止项目工作流 (workflow_stop)
   */
  async stopWorkflow(workflowId) {
    const result = await this.client.postAction('workflow_stop', { workflow_id: workflowId });
    await this.refresh(true);
    return result;
  }

  /**
   * 恢复暂停的项目工作流 (workflow_resume)
   */
  async resumeWorkflow(workflowId, messageId = null) {
    const args = { workflow_id: workflowId };
    if (messageId) args.message_id = messageId;
    const result = await this.client.postAction('workflow_resume', args);
    await this.refresh(true);
    return result;
  }

  /**
   * 唤醒当前经理进行一次巡检 (workflow_wake)
   */
  async wakeWorkflow(workflowId, note = null) {
    const args = { workflow_id: workflowId };
    if (note) args.note = note;
    const result = await this.client.postAction('workflow_wake', args);
    await this.refresh(true);
    return result;
  }

  /**
   * 紧急停止单个或全部 Agent (agent_halt)
   */
  async haltAgent(agent = '*', reason = '用户紧急停止') {
    const result = await this.client.postAction('agent_halt', {
      agent: agent || '*',
      reason: reason || '用户紧急停止'
    });
    await this.refresh(true);
    return result;
  }

  /**
   * 解除 Agent 启动锁 (agent_resume)
   */
  async resumeAgent(agent = '*') {
    const result = await this.client.postAction('agent_resume', {
      agent: agent || '*'
    });
    await this.refresh(true);
    return result;
  }

  /**
   * 发送消息 (send)
   * 自动生成或复用 request_key 防止重发
   */
  async sendMessage({ recipient, body, mode = 'queue', requestKey = null }) {

    const key = requestKey || this.client.generateRequestKey();
    const result = await this.client.postAction('send', {
      recipient,
      body: body?.trim(),
      mode,
      request_key: key
    });
    await this.refresh(true);
    return { result, requestKey: key };
  }

  /**
   * 单项开发任务授权执行
   * 按 recipient 身份严格分流至 codex_submit 或 antigravity_submit
   */
  async submitExecution({ agent, instruction, confirmed, taskId = null, sourceMessageId = null }) {
    if (!confirmed) throw new Error('必须明确勾选授权真实执行确认');

    const isCodex = ['deepseek-6', 'deepseek-7', 'deepseek-8'].includes(agent);
    const profile=this.rawState?.integrations?.agents.find(a=>a.id===agent);
    const actionName = profile&&profile.connection_id!=='deepseek-default'?'integration_submit':'deepseek_submit';

    const args = {
      agent,
      instruction,
      confirmed: true
    };
    if (taskId) args.task_id = taskId;
    if (sourceMessageId) args.source_message_id = sourceMessageId;

    const result = await this.client.postAction(actionName, args);
    await this.refresh(true);
    return result;
  }

  /**
   * 停止单项执行任务
   * 严格按真实 provider 分流至 codex_stop / antigravity_stop / deepseek_stop
   */
  async stopExecution(runId, explicitProvider = null) {
    if (!runId) throw new Error('停止执行必须提供 run_id');

    const provider = explicitProvider || this.resolveRunProvider(runId);
    if(provider?.startsWith('integration:')){const run=this.rawState?.integration_runs?.find(r=>r.id===runId);if(!run)throw Error('执行记录不存在');const result=await this.client.postAction('integration_stop',{agent:run.agent,run_id:runId});await this.refresh(true);return result;}
    let actionName = 'codex_stop';
    if (provider === 'antigravity') {
      actionName = 'antigravity_stop';
    } else if (provider === 'deepseek') {
      actionName = 'deepseek_stop';
    } else if (provider === 'codex') {
      actionName = 'codex_stop';
    } else {
      // 无法识别时抛出错误，避免误投 Antigravity 或 Codex
      throw new Error(`无法识别 run_id "${runId}" 的归属提供商，禁止盲目停止`);
    }

    const result = await this.client.postAction(actionName, { run_id: runId });
    await this.refresh(true);
    return result;
  }

  /**
   * 录入任务台账 (assign - 仅台账，非启动真实模型)
   */
  async assignTask({ agent, title }) {
    const result = await this.client.postAction('assign', { agent, title });
    await this.refresh(true);
    return result;
  }

  /**
   * 手动设置额度记录 (quota)
   */
  async setManualQuota({ agent, remaining, resetsAt = null }) {
    const args = {
      agent,
      remaining: remaining === '' || remaining === null ? null : Number(remaining),
      resets_at: resetsAt ? Math.floor(new Date(resetsAt).getTime() / 1000) : null
    };
    const result = await this.client.postAction('quota', args);
    await this.refresh(true);
    return result;
  }

  /**
   * 刷新 OpenAI 官方只读额度探测 (refresh_openai)
   */
  async refreshOpenAIQuota() {
    const result = await this.client.postAction('refresh_openai', {});
    await this.refresh(true);
    return result;
  }

  /**
   * 刷新 Antigravity 官方只读额度探测 (refresh_antigravity)
   */
  async refreshAntigravityQuota() {
    const result = await this.client.postAction('refresh_antigravity', {});
    await this.refresh(true);
    return result;
  }

  /**
   * DeepSeek API 密钥加密保存 (deepseek_save_key)
   */
  async saveDeepSeekKey(apiKey) {
    if (!apiKey || typeof apiKey !== 'string' || !apiKey.trim()) {
      throw new Error('API Key 不能为空');
    }
    const result = await this.client.postAction('deepseek_save_key', { api_key: apiKey.trim() });
    await this.refresh(true);
    return result;
  }

  /**
   * DeepSeek 官方接口只读连接验证 (deepseek_validate)
   */
  async validateDeepSeek() {
    const result = await this.client.postAction('deepseek_validate', {});
    await this.refresh(true);
    return result;
  }

  /**
   * DeepSeek 费用与权限配置授权 (deepseek_configure_api) - 默认无调用上限
   */
  async configureDeepSeekApi(config) {
    if (!config.confirmed) {
      throw new Error('必须明确勾选确认 DeepSeek 费用预算与权限');
    }
    const result = await this.client.postAction('deepseek_configure_api', {
      cwd: config.cwd,
      permission: config.permission || this.rawState?.deepseek?.config?.permission || 'workspace',
      max_runs: config.max_runs ? Number(config.max_runs) : 0,
      max_seconds: config.max_seconds ? Number(config.max_seconds) : 600,
      budget_cents: config.budget_cents ? Number(config.budget_cents) : 0,
      input_rate: Number(config.input_rate || 0),
      output_rate: Number(config.output_rate || 0),
      max_requests: config.max_requests ? Number(config.max_requests) : 0,
      max_output: config.max_output ? Number(config.max_output) : 0,
      enabled: Boolean(config.enabled),
      takeover: Boolean(config.takeover),
      confirmed: true
    });
    await this.refresh(true);
    return result;
  }

  /**
   * 一键切换项目经理（支持讨论与执行阶段，继承原经理上下文）
   */
  async switchManager({ workflowId = null, sessionId = null, targetManager = 'deepseek', inheritContext = true } = {}) {
    const args = {
      workflow_id: workflowId,
      session_id: sessionId,
      target_manager: targetManager,
      inherit_context: Boolean(inheritContext)
    };
    try {
      const result = await this.client.postAction('workflow_switch_manager', args);
      if (targetManager === 'deepseek' && workflowId) {
        try {
          await this.client.postAction('backup_authorize', { workflow_id: workflowId, confirmed: true });
        } catch (_) {}
      }
      await this.refresh(true);
      return result;
    } catch (error) {
      if (targetManager === 'deepseek' && workflowId && /unknown action|not found/i.test(error.message)) {
        const res = await this.client.postAction('backup_authorize', { workflow_id: workflowId, confirmed: true });
        await this.refresh(true);
        return res;
      }
      throw error;
    }
  }

  /**
   * 为已有工作流追加 DeepSeek 授权与备用接管 (backup_authorize)
   */
  async attachDeepSeekToWorkflow(workflowId) {
    const result = await this.client.postAction('backup_authorize', {
      workflow_id: workflowId,
      confirmed: true
    });
    await this.refresh(true);
    return result;
  }

  /**
   * 配置 Codex 独立授权 (codex_configure)
   */
  async configureCodex(config) {
    if (!config.confirmed) throw new Error('必须明确勾选确认 Codex 执行授权');
    const result = await this.client.postAction('codex_configure', config);
    await this.refresh(true);
    return result;
  }

  /**
   * 配置 Antigravity 独立授权 (antigravity_configure)
   */
  async configureAntigravity(config) {
    if (!config.confirmed) throw new Error('必须明确勾选确认 Antigravity 执行授权');
    const result = await this.client.postAction('antigravity_configure', config);
    await this.refresh(true);
    return result;
  }

  // --- 辅助时间格式化 ---

  _formatTime(timestampSec) {
    if (!timestampSec || typeof timestampSec !== 'number') return '无记录';
    const d = new Date(timestampSec * 1000);
    return isNaN(d.getTime()) ? '无效时间' : d.toLocaleString();
  }
}

// --- DOM 安全渲染辅助工具 (强制使用 textContent，禁止 innerHTML) ---

const SafeDOM = {
  /**
   * 创建元素并安全赋值 textContent
   */
  createElement(tag, textContent = '', className = '', attributes = {}) {
    if (typeof document === 'undefined') {
      return { tag, textContent, className, attributes };
    }
    const el = document.createElement(tag);
    if (['input','textarea','form'].includes(tag.toLowerCase()))el.setAttribute('autocomplete','off');
    if (textContent !== undefined && textContent !== null) {
      el.textContent = String(textContent);
    }
    if (className) {
      el.className = className;
    }
    for (const [k, v] of Object.entries(attributes)) {
      if (v !== undefined && v !== null) {
        el.setAttribute(k, String(v));
      }
    }
    return el;
  },

  /**
   * 安全更新元素的 textContent
   */
  setText(element, text) {
    if (!element) return;
    element.textContent = text !== undefined && text !== null ? String(text) : '';
  }
};

// 导出为浏览器全局对象与 CommonJS / ES 模块
if (typeof window !== 'undefined') {
  window.HubStateStore = HubStateStore;
  window.SafeDOM = SafeDOM;
}
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    HubStateStore,
    SafeDOM,
    ALL_AGENT_IDS,
    DEFAULT_AGENT_METAS
  };
}
